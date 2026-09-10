import { beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({
  session: vi.fn(),
  issue: vi.fn(),
  list: vi.fn(),
  getRequest: vi.fn(),
  getReport: vi.fn(),
  review: vi.fn(),
  getReview: vi.fn(),
  createProposal: vi.fn(),
  getProposal: vi.fn(),
  approveProposal: vi.fn(),
}));

vi.mock("@/lib/core-api/session", () => ({ getSessionToken: mocked.session }));
vi.mock("@/lib/core-api/external-result-workflow", () => ({
  issueExternalRelativeVolume: mocked.issue,
  listExternalRelativeVolumeRequests: mocked.list,
  getExternalRelativeVolumeRequest: mocked.getRequest,
  getExternalRelativeVolumeReport: mocked.getReport,
  reviewExternalRelativeVolumeReport: mocked.review,
  getExternalResultReview: mocked.getReview,
  createExternalReobservationProposal: mocked.createProposal,
  getExternalReobservationProposal: mocked.getProposal,
  approveExternalReobservationProposal: mocked.approveProposal,
}));

import { GET as listRequests, POST as issue } from "@/app/api/observation-work-orders/[workOrderId]/relative-volume-requests/route";
import { GET as getRequest } from "@/app/api/observation-work-orders/[workOrderId]/relative-volume-requests/[requestRef]/route";
import { GET as getReport } from "@/app/api/external-relative-volume-reports/[reportRef]/route";
import { POST as review } from "@/app/api/external-relative-volume-reports/[reportRef]/reviews/route";
import { GET as getReview } from "@/app/api/external-result-reviews/[reviewRef]/route";
import { POST as createProposal } from "@/app/api/external-reobservation-proposals/route";
import { GET as getProposal } from "@/app/api/external-reobservation-proposals/[proposalRef]/route";
import { POST as approveProposal } from "@/app/api/external-reobservation-proposals/approve/route";

const decisionRef = `external-use-decision-${"a".repeat(32)}`;
const requestRef = `external-relative-volume-${"b".repeat(32)}`;
const reportRef = `external-relative-volume-report-${"c".repeat(32)}`;
const reviewRef = `err-v1-${"d".repeat(64)}`;
const proposalRef = `erop-v1-${"e".repeat(64)}`;
const overlongRequestRef = `external-relative-volume-${"a".repeat(255)}`;
const overlongReportRef = `external-relative-volume-report-${"b".repeat(255)}`;
const requestContext = { params: Promise.resolve({ workOrderId: "work-1" }) };
const requestRefContext = { params: Promise.resolve({ workOrderId: "work-1", requestRef }) };
const reportContext = { params: Promise.resolve({ reportRef }) };
const reviewContext = { params: Promise.resolve({ reviewRef }) };
const proposalContext = { params: Promise.resolve({ proposalRef }) };

function post(body: unknown, headers: Record<string, string> = {}) {
  return new Request("http://console.test/api", {
    method: "POST",
    headers: { "content-type": "application/json", host: "console.test", ...headers },
    body: JSON.stringify(body),
  });
}

beforeEach(() => {
  vi.resetAllMocks();
  mocked.session.mockResolvedValue("token");
  mocked.issue.mockResolvedValue({ verdict: "ISSUED", request: { requestRef, status: "QUEUED" } });
  mocked.list.mockResolvedValue([]);
  mocked.getRequest.mockResolvedValue({ requestRef, status: "QUEUED" });
  mocked.getReport.mockResolvedValue({ report: { reportId: reportRef } });
  mocked.review.mockResolvedValue({ review: { reviewRef } });
  mocked.getReview.mockResolvedValue({ review: { reviewRef } });
  mocked.createProposal.mockResolvedValue({ proposal: { proposalRef, version: 1 } });
  mocked.getProposal.mockResolvedValue({ proposal: { proposalRef, version: 1 } });
  mocked.approveProposal.mockResolvedValue({ proposal: { proposalRef, version: 1 }, approvalReceipt: { successorWorkOrderId: "successor-1" } });
});

describe("external relative-volume workflow BFF", () => {
  it("rejects a cross-site volume issue before session or body processing", async () => {
    const response = await issue(new Request("http://console.test/api", { method: "POST", headers: { origin: "https://other.test", host: "console.test" } }) as never, requestContext);
    expect(response.status).toBe(403);
    expect(mocked.session).not.toHaveBeenCalled();
  });

  it("forwards only the exact Core issue reference and a stable idempotency key", async () => {
    const response = await issue(post({ decisionRef }, { "idempotency-key": "intent-key" }) as never, requestContext);
    expect(response.status).toBe(201);
    expect(mocked.issue).toHaveBeenCalledWith("work-1", decisionRef, "intent-key");
  });

  it.each([
    [{ decisionRef, organizationId: "spoof" }],
    [{ decisionRef: "other" }],
    [{}],
  ])("rejects non-Core issue input %j before forwarding", async (body) => {
    const response = await issue(post(body, { "idempotency-key": "intent-key" }) as never, requestContext);
    expect(response.status).toBe(400);
    expect(mocked.issue).not.toHaveBeenCalled();
  });

  it("keeps request/report/review reads scoped to their Core routes", async () => {
    expect((await listRequests(new Request("http://console.test/api") as never, requestContext)).status).toBe(200);
    expect((await getRequest(new Request("http://console.test/api") as never, requestRefContext)).status).toBe(200);
    expect((await getReport(new Request("http://console.test/api") as never, reportContext)).status).toBe(200);
    expect((await getReview(new Request("http://console.test/api") as never, reviewContext)).status).toBe(200);
    expect(mocked.list).toHaveBeenCalledWith("work-1");
    expect(mocked.getRequest).toHaveBeenCalledWith("work-1", requestRef);
    expect(mocked.getReport).toHaveBeenCalledWith(reportRef);
    expect(mocked.getReview).toHaveBeenCalledWith(reviewRef);
  });

  it("rejects Core request and report references whose complete identifier exceeds 255 characters", async () => {
    const overlongRequestContext = { params: Promise.resolve({ workOrderId: "work-1", requestRef: overlongRequestRef }) };
    const overlongReportContext = { params: Promise.resolve({ reportRef: overlongReportRef }) };
    expect((await getRequest(new Request("http://console.test/api") as never, overlongRequestContext)).status).toBe(404);
    expect((await getReport(new Request("http://console.test/api") as never, overlongReportContext)).status).toBe(404);
    expect(mocked.getRequest).not.toHaveBeenCalledWith("work-1", overlongRequestRef);
    expect(mocked.getReport).not.toHaveBeenCalledWith(overlongReportRef);
  });

  it("posts an empty human-review intent and never accepts browser authority fields", async () => {
    const response = await review(new Request("http://console.test/api", { method: "POST", headers: { host: "console.test" } }) as never, reportContext);
    expect(response.status).toBe(201);
    expect(mocked.review).toHaveBeenCalledWith(reportRef);
    const rejected = await review(post({ reportDigest: `sha256:${"a".repeat(64)}` }) as never, reportContext);
    expect(rejected.status).toBe(400);
  });

  it("forwards only one exact report-zone proposal target and retries approval with the exact version and key", async () => {
    const proposalResponse = await createProposal(post({ reportRef, targetWorkAreaIds: ["area-1"], reason: "현장 확인" }, { "idempotency-key": "proposal-key" }) as never);
    expect(proposalResponse.status).toBe(201);
    expect(mocked.createProposal).toHaveBeenCalledWith({ reportRef, targetWorkAreaIds: ["area-1"], reason: "현장 확인" }, "proposal-key");
    const approvalResponse = await approveProposal(post({ proposalRef, expectedVersion: 1 }, { "idempotency-key": "approval-key" }) as never);
    expect(approvalResponse.status).toBe(200);
    expect(mocked.approveProposal).toHaveBeenCalledWith(proposalRef, 1, "approval-key");
    expect((await getProposal(new Request("http://console.test/api") as never, proposalContext)).status).toBe(200);
  });

  it.each([
    [{ reportRef, targetWorkAreaIds: ["area-1", "area-2"], reason: "too many" }],
    [{ reportRef, targetWorkAreaIds: ["area-1"], authority: "spoof" }],
  ])("rejects proposal inputs outside Core's narrow DTO %j", async (body) => {
    const response = await createProposal(post(body, { "idempotency-key": "proposal-key" }) as never);
    expect(response.status).toBe(400);
    expect(mocked.createProposal).not.toHaveBeenCalled();
  });

  it.each([
    [{ proposalRef, expectedVersion: 0 }],
    [{ proposalRef, expectedVersion: 1, reportRef }],
  ])("rejects approval inputs outside Core's exact DTO %j", async (body) => {
    const response = await approveProposal(post(body, { "idempotency-key": "approval-key" }) as never);
    expect(response.status).toBe(400);
    expect(mocked.approveProposal).not.toHaveBeenCalled();
  });
});
