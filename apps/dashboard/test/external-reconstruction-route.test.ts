import { describe, expect, it, vi, beforeEach } from "vitest";

const mocked = vi.hoisted(() => ({
  session: vi.fn(), whoAmI: vi.fn(), workOrder: vi.fn(), progress: vi.fn(), externalContext: vi.fn(), list: vi.fn(), register: vi.fn(),
}));
vi.mock("@/lib/core-api/session", () => ({ getSessionToken: mocked.session }));
vi.mock("@/lib/core-api/auth", () => ({ whoAmI: mocked.whoAmI }));
vi.mock("@/lib/core-api/observation-work-orders", () => ({ getObservationWorkOrder: mocked.workOrder }));
vi.mock("@/lib/core-api/acquisition-coordination", () => ({ getAcquisitionProgress: mocked.progress }));
vi.mock("@/lib/core-api/external-reconstruction", () => ({
  getExternalReconstructionContext: mocked.externalContext,
  listExternalReconstructionSubmissions: mocked.list,
  registerExternalReconstructionSubmission: mocked.register,
}));

import { POST } from "@/app/api/observation-work-orders/[workOrderId]/external-reconstruction-submissions/route";

const context = { params: Promise.resolve({ workOrderId: "work-1" }) };
const body = { softwareName: "ODM", softwareVersion: "1.2.3", submissionId: "attempt-1", expectedEpochId: "epoch-1", submittedAt: "2026-09-08T01:02:03Z", captureStartedAt: null, captureEndedAt: null, artifacts: [{ artifactId: "ortho", kind: "ortho", fileName: "ortho.tif", format: "GeoTIFF", contentType: "application/octet-stream", declaredSha256: "a".repeat(64), declaredSizeBytes: 1, declaredCrs: null, declaredVerticalReference: null, declaredGsdM: null }] };

beforeEach(() => {
  vi.resetAllMocks();
  mocked.session.mockResolvedValue("token");
  mocked.whoAmI.mockResolvedValue({ principalId: "trusted-principal", organizationId: "trusted-org" });
  mocked.workOrder.mockResolvedValue({ workOrderId: "work-1", organizationId: "trusted-org", siteId: "trusted-site", cycleNumber: 1, version: 2, executionMode: "MANAGED_ACQUISITION" });
  mocked.externalContext.mockResolvedValue({ workOrderId: "work-1", siteId: "trusted-site", expectedEpochId: "epoch-1", cycleNumber: 1, workOrderVersion: 2, executionMode: "MANAGED_ACQUISITION" });
  mocked.progress.mockResolvedValue({ siteId: "trusted-site", analysisReadiness: { epoch: { epochId: "epoch-1" } } });
  mocked.list.mockResolvedValue([]);
  mocked.register.mockResolvedValue({ submissionRef: "opaque", state: "REGISTERED" });
});

function request(payload: unknown, headers: Record<string, string> = {}) {
  return new Request("http://console.test/api", { method: "POST", headers: { "content-type": "application/json", host: "console.test", ...headers }, body: JSON.stringify(payload) });
}
function rawRequest(body: string) {
  return new Request("http://console.test/api", { method: "POST", headers: { "content-type": "application/json", host: "console.test" }, body });
}
function invalidUtf8Request() {
  return new Request("http://console.test/api", { method: "POST", headers: { "content-type": "application/json", host: "console.test" }, body: new Uint8Array([0x7b, 0xff, 0x7d]) });
}

describe("external reconstruction collection BFF", () => {
  it("rejects cross-site requests before session lookup or body parsing", async () => {
    const response = await POST(new Request("http://console.test/api", { method: "POST", headers: { origin: "https://evil.test", host: "console.test" } }) as never, context);
    expect(response.status).toBe(403);
    expect(mocked.session).not.toHaveBeenCalled();
  });
  it("uses only trusted principal, organization, site, and epoch", async () => {
    const response = await POST(request(body) as never, context);
    expect(response.status).toBe(201);
    expect(mocked.session).toHaveBeenCalledBefore(mocked.register);
    const submitted = mocked.register.mock.calls[0][1];
    expect(submitted.organizationId).toBe("trusted-org");
    expect(submitted.siteId).toBe("trusted-site");
    expect(submitted.submittedBy).toBe("trusted-principal");
    expect(submitted.observationEpochId).toBe("epoch-1");
    expect(submitted.producerDeclaration.softwareName).toBe("ODM");
    expect(submitted.producerDeclaration.softwareVersion).toBe("1.2.3");
    expect(submitted.submissionDigest).toMatch(/^sha256:[0-9a-f]{64}$/);
  });
  it("rejects BFF-owned identity claims and other unknown body fields before Core calls", async () => {
    const response = await POST(request({ ...body, organizationId: "spoof" }) as never, context);
    expect(response.status).toBe(400);
    expect(mocked.whoAmI).not.toHaveBeenCalled();
    expect(mocked.register).not.toHaveBeenCalled();
  });
  it("carries a header-read CRS declaration into the sealed submission", async () => {
    const withCrs = { ...body, artifacts: [{ ...body.artifacts[0], declaredCrs: "EPSG:5186" }] };
    expect((await POST(request(withCrs) as never, context)).status).toBe(201);
    const declared = mocked.register.mock.calls[0][1];
    expect(declared.artifacts[0].declaredCrs).toBe("EPSG:5186");
    expect((await POST(request(body) as never, context)).status).toBe(201);
    expect(mocked.register.mock.calls[1][1].submissionDigest).not.toBe(declared.submissionDigest);
  });
  it.each([
    ["an empty CRS", { declaredCrs: "" }],
    ["an untrimmed CRS that Core would normalise", { declaredCrs: " EPSG:5186" }],
    ["an over-long CRS", { declaredCrs: "E".repeat(256) }],
    ["a non-text CRS", { declaredCrs: 5186 }],
    ["a GSD declaration", { declaredGsdM: 0.05 }],
    ["a vertical reference declaration", { declaredVerticalReference: { source: "USER_DECLARED" } }],
  ])("rejects %s before Core calls", async (_label, override) => {
    const response = await POST(request({ ...body, artifacts: [{ ...body.artifacts[0], ...override }] }) as never, context);
    expect(response.status).toBe(400);
    expect(mocked.register).not.toHaveBeenCalled();
  });
  it("enforces the JSON byte limit while streaming before Core calls", async () => {
    const response = await POST(request({ ...body, padding: "x".repeat(2 * 1024 * 1024) }) as never, context);
    expect(response.status).toBe(413);
    expect(mocked.whoAmI).not.toHaveBeenCalled();
    expect(mocked.register).not.toHaveBeenCalled();
  });
  it.each([
    ["malformed JSON", rawRequest("{" )],
    ["malformed UTF-8", invalidUtf8Request()],
    ["missing artifact field", request({ ...body, artifacts: [{ ...body.artifacts[0], declaredGsdM: undefined }] })],
    ["unsafe integer", request({ ...body, artifacts: [{ ...body.artifacts[0], declaredSizeBytes: Number.MAX_SAFE_INTEGER + 1 }] })],
    ["non-finite integer", rawRequest(JSON.stringify(body).replace('"declaredSizeBytes":1', '"declaredSizeBytes":1e999'))],
  ])("rejects %s before Core calls", async (_label, invalidRequest) => {
    const response = await POST(invalidRequest as never, context);
    expect(response.status).toBe(400);
    expect(mocked.whoAmI).not.toHaveBeenCalled();
    expect(mocked.register).not.toHaveBeenCalled();
  });
  it("fails stale client epochs without posting", async () => {
    const response = await POST(request({ ...body, expectedEpochId: "old" }) as never, context);
    expect(response.status).toBe(409);
    expect(mocked.register).not.toHaveBeenCalled();
  });
  it("rejects an equal capture interval before Core calls", async () => {
    const response = await POST(request({
      ...body,
      captureStartedAt: "2026-09-08T01:00:00Z",
      captureEndedAt: "2026-09-08T01:00:00Z",
    }) as never, context);
    expect(response.status).toBe(400);
    expect(mocked.register).not.toHaveBeenCalled();
  });
  it("recovers a lost 201 only when the later list has the exact digest", async () => {
    mocked.register.mockRejectedValueOnce(new Error("lost response"));
    mocked.list.mockResolvedValueOnce([]).mockImplementationOnce(async () => [{
      submissionRef: "opaque", state: "REGISTERED", submission: mocked.register.mock.calls[0][1],
    }]);
    const response = await POST(request(body) as never, context);
    expect(response.status).toBe(200);
    expect(mocked.register).toHaveBeenCalledTimes(1);
  });
  it("does not post when a retry reuses the id with a different stored declaration", async () => {
    mocked.list.mockResolvedValue([{ submissionRef: "opaque", state: "REGISTERED", submission: { submissionId: "attempt-1", revision: 1, submissionDigest: "sha256:" + "0".repeat(64) } }]);
    const response = await POST(request(body) as never, context);
    expect(response.status).toBe(409);
    expect(mocked.register).not.toHaveBeenCalled();
  });

  it("resumes an exact old-epoch record before rejecting a new stale attempt", async () => {
    await POST(request(body) as never, context);
    const old = mocked.register.mock.calls[0][1];
    mocked.externalContext.mockResolvedValue({ workOrderId: "work-1", siteId: "trusted-site", expectedEpochId: "epoch-2", cycleNumber: 1, workOrderVersion: 2, executionMode: "MANAGED_ACQUISITION" });
    mocked.list.mockResolvedValue([{ submissionRef: "opaque", state: "REGISTERED", submission: old }]);
    const response = await POST(request(body) as never, context);
    expect(response.status).toBe(200);
    expect(mocked.register).toHaveBeenCalledTimes(1);
  });

});

it("registers an external successor without asking for acquisition execution", async () => {
  mocked.progress.mockRejectedValue(new Error("EXTERNAL_REOBSERVATION_PLANNING_ONLY"));
  const response = await POST(request(body) as never, context);
  expect(response.status).toBe(201);
  expect(mocked.externalContext).toHaveBeenCalledWith("work-1");
  expect(mocked.progress).not.toHaveBeenCalled();
});

it.each([
  { workOrderId: "other" }, { siteId: "foreign" }, { cycleNumber: 2 }, { workOrderVersion: 3 },
])("rejects a crossed or stale external context %j", async (changed) => {
  mocked.externalContext.mockResolvedValue({ workOrderId: "work-1", siteId: "trusted-site", expectedEpochId: "epoch-1", cycleNumber: 1, workOrderVersion: 2, executionMode: "MANAGED_ACQUISITION", ...changed });
  const response = await POST(request(body) as never, context);
  expect([404, 409]).toContain(response.status);
  expect(mocked.register).not.toHaveBeenCalled();
});
