import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({
  session: vi.fn(),
  decision: vi.fn(),
  issue: vi.fn(),
  list: vi.fn(),
  getRequest: vi.fn(),
  getReport: vi.fn(),
  history: vi.fn(),
  review: vi.fn(),
  share: vi.fn(),
}));

vi.mock("@/lib/core-api/session", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/core-api/session")>();
  return { ...actual, getSessionToken: mocked.session };
});
vi.mock("@/lib/core-api/external-reconstruction", () => ({ requestExternalSingleVolumeDecision: mocked.decision }));
vi.mock("@/lib/core-api/external-result-workflow", () => ({
  issueExternalSingleVolume: mocked.issue,
  listExternalSingleVolumeRequests: mocked.list,
  getExternalSingleVolumeRequest: mocked.getRequest,
  getExternalSingleVolumeReport: mocked.getReport,
  listSiteExternalVolumeHistory: mocked.history,
  reviewExternalSingleVolumeReport: mocked.review,
}));
vi.mock("@/lib/core-api/work-collaboration", () => ({ shareExternalSingleVolumeReport: mocked.share }));

import { POST as decide } from "@/app/api/observation-work-orders/[workOrderId]/external-reconstruction-submissions/[submissionRef]/revisions/[revision]/use-decisions/single-volume/route";
import { GET as listRequests, POST as issue } from "@/app/api/observation-work-orders/[workOrderId]/single-volume-requests/route";
import { GET as getRequest } from "@/app/api/observation-work-orders/[workOrderId]/single-volume-requests/[requestRef]/route";
import { GET as getReport } from "@/app/api/external-single-volume-reports/[reportRef]/route";
import { POST as review } from "@/app/api/external-single-volume-reports/[reportRef]/reviews/route";
import { POST as share } from "@/app/api/external-single-volume-reports/[reportRef]/shares/route";
import { GET as getHistory } from "@/app/api/sites/[siteId]/external-volume-reports/route";

const decisionRef = `external-use-decision-${"a".repeat(32)}`;
const requestRef = `external-single-volume-${"b".repeat(32)}`;
const reportRef = `external-single-volume-report-${"c".repeat(32)}`;
const relativeReportRef = `external-relative-volume-report-${"d".repeat(32)}`;
const overlongRequestRef = `external-single-volume-${"a".repeat(255)}`;
const overlongReportRef = `external-single-volume-report-${"b".repeat(255)}`;
const submissionRef = `ers-v1-${"e".repeat(64)}`;

const decisionContext = { params: Promise.resolve({ workOrderId: "work-1", submissionRef, revision: "1" }) };
const requestContext = { params: Promise.resolve({ workOrderId: "work-1" }) };
const requestRefContext = { params: Promise.resolve({ workOrderId: "work-1", requestRef }) };
const reportContext = { params: Promise.resolve({ reportRef }) };
const relativeReportContext = { params: Promise.resolve({ reportRef: relativeReportRef }) };
const siteContext = { params: Promise.resolve({ siteId: "site-1" }) };

function post(body: unknown, headers: Record<string, string> = {}) {
  return new Request("http://console.test/api", {
    method: "POST",
    headers: { "content-type": "application/json", host: "console.test", ...headers },
    body: JSON.stringify(body),
  });
}

function get(url = "http://console.test/api") {
  return new NextRequest(url);
}

beforeEach(() => {
  vi.resetAllMocks();
  mocked.session.mockResolvedValue("token");
  mocked.decision.mockResolvedValue({ decision: { decisionId: decisionRef, verdict: "ELIGIBLE" } });
  mocked.issue.mockResolvedValue({ verdict: "ISSUED", request: { requestRef, status: "QUEUED" }, detail: null });
  mocked.list.mockResolvedValue([]);
  mocked.getRequest.mockResolvedValue({ requestRef, status: "QUEUED" });
  mocked.getReport.mockResolvedValue({ report: { reportId: reportRef } });
  mocked.history.mockResolvedValue({ items: [], nextCursor: null });
  mocked.review.mockResolvedValue({ review: { reviewRef: `err-v1-${"d".repeat(64)}` } });
  mocked.share.mockResolvedValue({ shareRef: `ers-share-${"e".repeat(32)}` });
});

describe("external single-volume use-decision BFF", () => {
  it("rejects a cross-site decision request before session or body processing", async () => {
    const response = await decide(new Request("http://console.test/api", { method: "POST", headers: { origin: "https://other.test", host: "console.test" } }) as never, decisionContext);
    expect(response.status).toBe(403);
    expect(mocked.session).not.toHaveBeenCalled();
  });

  it("rejects a malformed submission reference or revision before session-scoped calls", async () => {
    const badSubmission = { params: Promise.resolve({ workOrderId: "work-1", submissionRef: "not-a-ref", revision: "1" }) };
    const badRevision = { params: Promise.resolve({ workOrderId: "work-1", submissionRef, revision: "0" }) };
    expect((await decide(post({ zoneId: "zone-1" }, { "idempotency-key": "key-1" }) as never, badSubmission)).status).toBe(404);
    expect((await decide(post({ zoneId: "zone-1" }, { "idempotency-key": "key-1" }) as never, badRevision)).status).toBe(404);
    expect(mocked.decision).not.toHaveBeenCalled();
  });

  it("forwards only the exact Core zoneId and a stable idempotency key", async () => {
    const response = await decide(post({ zoneId: "zone-1" }, { "idempotency-key": "intent-key" }) as never, decisionContext);
    expect(response.status).toBe(201);
    expect(mocked.decision).toHaveBeenCalledWith("work-1", submissionRef, 1, "zone-1", "intent-key");
  });

  it("rejects a missing idempotency key before forwarding", async () => {
    const response = await decide(post({ zoneId: "zone-1" }) as never, decisionContext);
    expect(response.status).toBe(400);
    expect(mocked.decision).not.toHaveBeenCalled();
  });

  it.each([
    [{ zoneId: "zone-1", extra: "spoof" }],
    [{ zoneId: "" }],
    [{ zoneId: "z".repeat(256) }],
    [{ zoneId: 1 }],
    [{}],
  ])("rejects non-Core decision input %j before forwarding", async (body) => {
    const response = await decide(post(body, { "idempotency-key": "intent-key" }) as never, decisionContext);
    expect(response.status).toBe(400);
    expect(mocked.decision).not.toHaveBeenCalled();
  });

  it("passes a Core idempotency conflict through unmodified", async () => {
    const { CoreApiError } = await import("@/lib/core-api/client");
    mocked.decision.mockRejectedValue(new CoreApiError(409, { verdict: "IDEMPOTENCY_CONFLICT" }));
    const response = await decide(post({ zoneId: "zone-1" }, { "idempotency-key": "intent-key" }) as never, decisionContext);
    expect(response.status).toBe(409);
  });
});

describe("external single-volume request BFF", () => {
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

  it("rejects a missing idempotency key before forwarding", async () => {
    const response = await issue(post({ decisionRef }) as never, requestContext);
    expect(response.status).toBe(400);
    expect(mocked.issue).not.toHaveBeenCalled();
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

  it("passes a Core idempotency conflict through unmodified", async () => {
    const { CoreApiError } = await import("@/lib/core-api/client");
    mocked.issue.mockRejectedValue(new CoreApiError(409, { verdict: "IDEMPOTENCY_CONFLICT" }));
    const response = await issue(post({ decisionRef }, { "idempotency-key": "intent-key" }) as never, requestContext);
    expect(response.status).toBe(409);
  });

  it("keeps request and report reads scoped to their Core routes", async () => {
    expect((await listRequests(get() as never, requestContext)).status).toBe(200);
    expect((await getRequest(get() as never, requestRefContext)).status).toBe(200);
    expect((await getReport(get() as never, reportContext)).status).toBe(200);
    expect(mocked.list).toHaveBeenCalledWith("work-1");
    expect(mocked.getRequest).toHaveBeenCalledWith("work-1", requestRef);
    expect(mocked.getReport).toHaveBeenCalledWith(reportRef);
  });

  it("rejects Core request and report references whose complete identifier exceeds 255 characters", async () => {
    const overlongRequestContext = { params: Promise.resolve({ workOrderId: "work-1", requestRef: overlongRequestRef }) };
    const overlongReportContext = { params: Promise.resolve({ reportRef: overlongReportRef }) };
    expect((await getRequest(get() as never, overlongRequestContext)).status).toBe(404);
    expect((await getReport(get() as never, overlongReportContext)).status).toBe(404);
    expect(mocked.getRequest).not.toHaveBeenCalledWith("work-1", overlongRequestRef);
    expect(mocked.getReport).not.toHaveBeenCalledWith(overlongReportRef);
  });

  it("rejects a relative-volume reference on the single-volume request/report routes", async () => {
    const relativeRequestRef = `external-relative-volume-${"b".repeat(32)}`;
    const crossKindRequestContext = { params: Promise.resolve({ workOrderId: "work-1", requestRef: relativeRequestRef }) };
    const crossKindReportContext = { params: Promise.resolve({ reportRef: relativeReportRef }) };
    expect((await getRequest(get() as never, crossKindRequestContext)).status).toBe(404);
    expect((await getReport(get() as never, crossKindReportContext)).status).toBe(404);
    expect(mocked.getRequest).not.toHaveBeenCalled();
    expect(mocked.getReport).not.toHaveBeenCalled();
  });
});

describe("external single-volume review BFF", () => {
  it("rejects a cross-site review request before session or body processing", async () => {
    const response = await review(new Request("http://console.test/api", { method: "POST", headers: { origin: "https://other.test", host: "console.test" } }) as never, reportContext);
    expect(response.status).toBe(403);
    expect(mocked.session).not.toHaveBeenCalled();
  });

  it("posts an empty human-review intent and never accepts browser authority fields", async () => {
    const response = await review(new Request("http://console.test/api", { method: "POST", headers: { host: "console.test" } }) as never, reportContext);
    expect(response.status).toBe(201);
    expect(mocked.review).toHaveBeenCalledWith(reportRef);
    const rejected = await review(post({ reportDigest: `sha256:${"a".repeat(64)}` }) as never, reportContext);
    expect(rejected.status).toBe(400);
  });

  it("rejects a relative-volume reference on the single-volume review route", async () => {
    const response = await review(new Request("http://console.test/api", { method: "POST", headers: { host: "console.test" } }) as never, relativeReportContext);
    expect(response.status).toBe(400);
    expect(mocked.review).not.toHaveBeenCalled();
  });

  it("passes a Core review conflict through unmodified", async () => {
    const { CoreApiError } = await import("@/lib/core-api/client");
    mocked.review.mockRejectedValue(new CoreApiError(409, { verdict: "EXTERNAL_RESULT_REVIEW_SOURCE_UNAVAILABLE" }));
    const response = await review(new Request("http://console.test/api", { method: "POST", headers: { host: "console.test" } }) as never, reportContext);
    expect(response.status).toBe(409);
  });
});

describe("external single-volume share BFF", () => {
  it("rejects a cross-site share request before session or body processing", async () => {
    const response = await share(new Request("http://console.test/api", { method: "POST", headers: { origin: "https://other.test", host: "console.test" } }) as never, reportContext);
    expect(response.status).toBe(403);
    expect(mocked.session).not.toHaveBeenCalled();
  });

  it("rejects a missing recipient before forwarding", async () => {
    const response = await share(post({}, { "idempotency-key": "share-1" }) as never, reportContext);
    expect(response.status).toBe(400);
    expect(mocked.share).not.toHaveBeenCalled();
  });

  it("rejects a relative-volume reference on the single-volume share route", async () => {
    const response = await share(post({ recipientPrincipalId: "operator-b" }, { "idempotency-key": "share-1" }) as never, relativeReportContext);
    expect(response.status).toBe(404);
    expect(mocked.share).not.toHaveBeenCalled();
  });

  it("forwards only the exact report reference, recipient and idempotency key", async () => {
    const response = await share(post({ recipientPrincipalId: "operator-b" }, { "idempotency-key": "share-1" }) as never, reportContext);
    expect(response.status).toBe(201);
    expect(mocked.share).toHaveBeenCalledWith(reportRef, "operator-b", "share-1");
  });

  it("passes a Core share conflict through unmodified", async () => {
    const { CoreApiError } = await import("@/lib/core-api/client");
    mocked.share.mockRejectedValue(new CoreApiError(409, { verdict: "IDEMPOTENCY_CONFLICT" }));
    const response = await share(post({ recipientPrincipalId: "operator-b" }, { "idempotency-key": "share-1" }) as never, reportContext);
    expect(response.status).toBe(409);
  });
});

describe("merged site external volume history BFF", () => {
  it("accepts a relative-volume report ref as the merged cursor", async () => {
    const response = await getHistory(get(`http://console.test/api?after=${relativeReportRef}`) as never, siteContext);
    expect(response.status).toBe(200);
    expect(mocked.history).toHaveBeenCalledWith("site-1", { after: relativeReportRef, limit: undefined });
  });

  it("accepts a single-volume report ref as the merged cursor", async () => {
    const response = await getHistory(get(`http://console.test/api?after=${reportRef}`) as never, siteContext);
    expect(response.status).toBe(200);
    expect(mocked.history).toHaveBeenCalledWith("site-1", { after: reportRef, limit: undefined });
  });

  it("rejects a malformed cursor before calling Core", async () => {
    const response = await getHistory(get("http://console.test/api?after=not-a-ref") as never, siteContext);
    expect(response.status).toBe(404);
    expect(mocked.history).not.toHaveBeenCalled();
  });

  it("rejects a limit outside 1..50 before calling Core", async () => {
    const response = await getHistory(get("http://console.test/api?limit=51") as never, siteContext);
    expect(response.status).toBe(400);
    expect(mocked.history).not.toHaveBeenCalled();
  });

  it("forwards a valid numeric limit", async () => {
    const response = await getHistory(get("http://console.test/api?limit=10") as never, siteContext);
    expect(response.status).toBe(200);
    expect(mocked.history).toHaveBeenCalledWith("site-1", { after: undefined, limit: 10 });
  });
});
