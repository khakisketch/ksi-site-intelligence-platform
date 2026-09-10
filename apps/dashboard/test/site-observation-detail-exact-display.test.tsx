/** @vitest-environment jsdom */
import { cleanup, render, screen } from "@testing-library/react";
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
  it("uses the exact verified report for a safe display pair and retained successor operation state", async () => {
    render(await SiteObservationDetailPage({ params: Promise.resolve({ siteId: "site-1", reportRef }) }));
    expect(screen.getByTestId("display-pair").textContent).toBe("READY");
    expect(mocked.pair).toHaveBeenCalledWith(expect.anything(), { organizationId: "org-1", siteId: "site-1" });
    expect(mocked.operations).toHaveBeenCalledWith("successor-1");
    expect(screen.getByTestId("successor-state").textContent).toBe("CLOSED");
    expect(mocked.share).toHaveBeenCalledWith({ reportRef, siteId: "site-1", organizationId: "org-1", principalId: "operator-1", canWrite: true });
  });

  it("fails closed and leaves successor state unverified when the full report digest diverges from the site projection", async () => {
    mocked.detail.mockResolvedValue(fullReport(digest("0")));
    render(await SiteObservationDetailPage({ params: Promise.resolve({ siteId: "site-1", reportRef }) }));
    expect(screen.getByTestId("display-pair").textContent).toBe("UNAVAILABLE");
    expect(mocked.pair).not.toHaveBeenCalled();
    expect(mocked.operations).not.toHaveBeenCalled();
    expect(screen.getByTestId("successor-state").textContent).toBe("none");
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
    expect(screen.getByTestId("display-pair").textContent).toBe("UNAVAILABLE");
    expect(mocked.pair).not.toHaveBeenCalled();
    expect(mocked.operations).not.toHaveBeenCalled();
    expect(screen.getByTestId("successor-state").textContent).toBe("none");
    expect(mocked.share).not.toHaveBeenCalled();
  });

  it("fails closed when a report detail echoes a foreign organization instead of the resolved operator scope", async () => {
    const foreignDetail = fullReport();
    foreignDetail.request.baseline.subject.organizationId = "foreign-org";
    foreignDetail.request.current.subject.organizationId = "foreign-org";
    mocked.detail.mockResolvedValue(foreignDetail);
    render(await SiteObservationDetailPage({ params: Promise.resolve({ siteId: "site-1", reportRef }) }));
    expect(screen.getByTestId("display-pair").textContent).toBe("UNAVAILABLE");
    expect(mocked.pair).not.toHaveBeenCalled();
    expect(mocked.operations).not.toHaveBeenCalled();
    expect(screen.getByTestId("successor-state").textContent).toBe("none");
    expect(mocked.share).not.toHaveBeenCalled();
  });

  it("preserves read-only permission for an exact report viewer", async () => {
    mocked.session.mockResolvedValue({ kind: "ready", principal: { organizationId: "org-1", principalId: "viewer-1", permissions: ["SITES_READ"] } });
    render(await SiteObservationDetailPage({ params: Promise.resolve({ siteId: "site-1", reportRef }) }));
    expect(mocked.share).toHaveBeenCalledWith(expect.objectContaining({ principalId: "viewer-1", canWrite: false }));
  });
});
