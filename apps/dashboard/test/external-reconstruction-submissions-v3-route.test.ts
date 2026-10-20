import { describe, expect, it, vi, beforeEach } from "vitest";

const mocked = vi.hoisted(() => ({
  session: vi.fn(), whoAmI: vi.fn(), workOrder: vi.fn(), externalContext: vi.fn(), list: vi.fn(), register: vi.fn(),
}));
vi.mock("@/lib/core-api/session", () => ({ getSessionToken: mocked.session }));
vi.mock("@/lib/core-api/auth", () => ({ whoAmI: mocked.whoAmI }));
vi.mock("@/lib/core-api/observation-work-orders", () => ({ getObservationWorkOrder: mocked.workOrder }));
vi.mock("@/lib/core-api/external-reconstruction", () => ({
  getExternalReconstructionContext: mocked.externalContext,
  listExternalReconstructionSubmissions: mocked.list,
  registerExternalReconstructionSubmissionV3: mocked.register,
}));

import { POST } from "@/app/api/observation-work-orders/[workOrderId]/external-reconstruction-submissions-v3/route";

const context = { params: Promise.resolve({ workOrderId: "work-1" }) };
const hex = (value: string) => value.repeat(64);
const orthoArtifact = { artifactId: "ortho", kind: "ortho", fileName: "ortho.tif", format: "GeoTIFF", contentType: "application/octet-stream", declaredSha256: hex("a"), declaredSizeBytes: 1, declaredCrs: null, declaredVerticalReference: null, declaredGsdM: null };
const body = {
  softwareName: "ODM", softwareVersion: "1.2.3", sourceNote: null, producerKnowledge: "DECLARED",
  submissionId: "attempt-1", expectedEpochId: "epoch-1", submittedAt: "2026-09-08T01:02:03Z",
  captureBasis: "EXACT_INTERVAL", captureStartedAt: "2026-09-08T01:00:00Z", captureEndedAt: "2026-09-08T01:10:00Z", captureDate: null,
  originalRetentionLocus: "customer_workstation", originalRetentionDetail: null,
  upstreamSource: null, derivativeExport: null,
  artifacts: [orthoArtifact],
};

beforeEach(() => {
  vi.resetAllMocks();
  mocked.session.mockResolvedValue("token");
  mocked.whoAmI.mockResolvedValue({ principalId: "trusted-principal", organizationId: "trusted-org" });
  mocked.workOrder.mockResolvedValue({ workOrderId: "work-1", organizationId: "trusted-org", siteId: "trusted-site", cycleNumber: 1, version: 2, executionMode: "MANAGED_ACQUISITION" });
  mocked.externalContext.mockResolvedValue({ workOrderId: "work-1", siteId: "trusted-site", expectedEpochId: "epoch-1", cycleNumber: 1, workOrderVersion: 2, executionMode: "MANAGED_ACQUISITION" });
  mocked.list.mockResolvedValue([]);
  mocked.register.mockResolvedValue({ submissionRef: "opaque", state: "REGISTERED" });
});

function request(payload: unknown, headers: Record<string, string> = {}) {
  return new Request("http://console.test/api", { method: "POST", headers: { "content-type": "application/json", host: "console.test", ...headers }, body: JSON.stringify(payload) });
}
function rawRequest(body: string) {
  return new Request("http://console.test/api", { method: "POST", headers: { "content-type": "application/json", host: "console.test" }, body });
}

describe("external reconstruction V3 collection BFF", () => {
  it("rejects cross-site requests before session lookup or body parsing", async () => {
    const response = await POST(new Request("http://console.test/api", { method: "POST", headers: { origin: "https://evil.test", host: "console.test" } }) as never, context);
    expect(response.status).toBe(403);
    expect(mocked.session).not.toHaveBeenCalled();
  });
  it("uses only trusted principal, organization, site, and epoch with the fixed V3 intake constants", async () => {
    const response = await POST(request(body) as never, context);
    expect(response.status).toBe(201);
    expect(mocked.session).toHaveBeenCalledBefore(mocked.register);
    const submitted = mocked.register.mock.calls[0][1];
    expect(submitted.contractVersion).toBe("external-reconstruction-submission.v3");
    expect(submitted.organizationId).toBe("trusted-org");
    expect(submitted.siteId).toBe("trusted-site");
    expect(submitted.submittedBy).toBe("trusted-principal");
    expect(submitted.observationEpochId).toBe("epoch-1");
    // Intake identity stays a fixed customer-submitted constant, never a run-location fact.
    expect(submitted.executionResponsibility).toBe("customer_operator");
    expect(submitted.executionLocus).toBe("customer_workstation");
    expect(submitted.producerDeclaration.producerKnowledge).toBe("DECLARED");
    expect(submitted.inputDeclaration.captureBasis).toBe("EXACT_INTERVAL");
    expect(submitted.inputDeclaration.rawMediaStoredByKsi).toBe(false);
    expect(submitted.submissionDigest).toMatch(/^sha256:[0-9a-f]{64}$/);
  });
  it("rejects BFF-owned identity claims and other unknown body fields before Core calls", async () => {
    const response = await POST(request({ ...body, organizationId: "spoof" }) as never, context);
    expect(response.status).toBe(400);
    expect(mocked.whoAmI).not.toHaveBeenCalled();
    expect(mocked.register).not.toHaveBeenCalled();
  });
  it("accepts a date-only declaration with null timestamps while keeping the calendar date", async () => {
    const dateOnly = {
      ...body,
      producerKnowledge: "UNKNOWN", softwareName: null, softwareVersion: null,
      captureBasis: "DATE_ONLY", captureStartedAt: null, captureEndedAt: null, captureDate: "2021-05-17",
      originalRetentionLocus: "upstream_source", originalRetentionDetail: "portal keeps originals",
      upstreamSource: { sourceUri: "https://example.invalid/source/ortho.tif", sourceSha256: hex("c"), licenceDeclaration: null, retrievalNote: null },
      derivativeExport: null,
      artifacts: [{ ...orthoArtifact, artifactId: "dsm", kind: "dsm", fileName: "surface.tif", declaredSha256: hex("b"), declaredSizeBytes: 2, declaredCrs: "EPSG:5186" }],
    };
    const response = await POST(request(dateOnly) as never, context);
    expect(response.status).toBe(201);
    const submitted = mocked.register.mock.calls[0][1];
    expect(submitted.inputDeclaration.captureDate).toBe("2021-05-17");
    expect(submitted.inputDeclaration.captureStartedAt).toBeNull();
    expect(submitted.inputDeclaration.captureEndedAt).toBeNull();
    expect(submitted.producerDeclaration.producerKnowledge).toBe("UNKNOWN");
    expect(JSON.stringify(submitted)).not.toContain("T00:00:00");
  });
  it("accepts a DSM-only package without inventing an ortho artifact", async () => {
    const dsmOnly = {
      ...body,
      artifacts: [{ ...orthoArtifact, artifactId: "dsm", kind: "dsm", fileName: "surface.tif", declaredSha256: hex("b"), declaredSizeBytes: 2 }],
    };
    const response = await POST(request(dsmOnly) as never, context);
    expect(response.status).toBe(201);
    expect(mocked.register.mock.calls[0][1].artifacts).toHaveLength(1);
  });
  it.each([
    ["DATE_ONLY with timestamps", { captureBasis: "DATE_ONLY", captureStartedAt: "2026-09-08T01:00:00Z", captureEndedAt: "2026-09-08T01:10:00Z", captureDate: "2026-09-08" }],
    ["EXACT_INTERVAL with a calendar date", { captureBasis: "EXACT_INTERVAL", captureDate: "2026-09-08" }],
    ["EXACT_INTERVAL with an equal pair", { captureBasis: "EXACT_INTERVAL", captureStartedAt: "2026-09-08T01:00:00Z", captureEndedAt: "2026-09-08T01:00:00Z" }],
    ["UNKNOWN with a date", { captureBasis: "UNKNOWN", captureDate: "2026-09-08" }],
    ["PARTIAL with a version", { producerKnowledge: "PARTIAL", softwareName: "ODM", softwareVersion: "1" }],
    ["PARTIAL without a name", { producerKnowledge: "PARTIAL", softwareName: null, softwareVersion: null }],
    ["UNKNOWN with a name", { producerKnowledge: "UNKNOWN", softwareName: "ODM", softwareVersion: null }],
    ["fabricated unknown name", { producerKnowledge: "DECLARED", softwareName: "unknown", softwareVersion: "1" }],
    ["fabricated unknown version", { producerKnowledge: "DECLARED", softwareName: "ODM", softwareVersion: "Unknown" }],
    ["unknown retention locus value", { originalRetentionLocus: "publisher_holding" }],
    ["an unsafe source scheme", { upstreamSource: { sourceUri: "ftp://example.invalid/x.tif", sourceSha256: null, licenceDeclaration: null, retrievalNote: null } }],
    ["a credentialed source URI", { upstreamSource: { sourceUri: "https://user@example.invalid/x.tif", sourceSha256: null, licenceDeclaration: null, retrievalNote: null } }],
    ["a bad export digest", { derivativeExport: { toolName: "GDAL", toolVersion: "3.8.0", settingsDigest: "abc", exportedAt: null, exportNote: null } }],
    ["two orthos", { artifacts: [orthoArtifact, { ...orthoArtifact, declaredSha256: hex("b"), declaredSizeBytes: 2 }] }],
    ["no artifacts", { artifacts: [] }],
    ["a non-declared artifact kind", { artifacts: [{ ...orthoArtifact, artifactId: "cloud", kind: "point_cloud" }] }],
  ])("rejects %s before Core calls", async (_label, override) => {
    const response = await POST(request({ ...body, ...override }) as never, context);
    expect(response.status).toBe(400);
    expect(mocked.register).not.toHaveBeenCalled();
  });
  it("rejects malformed JSON and oversized bodies before Core calls", async () => {
    expect((await POST(rawRequest("{") as never, context)).status).toBe(400);
    expect((await POST(request({ ...body, padding: "x".repeat(2 * 1024 * 1024) }) as never, context)).status).toBe(413);
    expect(mocked.register).not.toHaveBeenCalled();
  });
  it("fails stale client epochs without posting", async () => {
    const response = await POST(request({ ...body, expectedEpochId: "old" }) as never, context);
    expect(response.status).toBe(409);
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
  it("resumes an exact old-epoch V3 record before rejecting a new stale attempt", async () => {
    await POST(request(body) as never, context);
    const old = mocked.register.mock.calls[0][1];
    mocked.externalContext.mockResolvedValue({ workOrderId: "work-1", siteId: "trusted-site", expectedEpochId: "epoch-2", cycleNumber: 1, workOrderVersion: 2, executionMode: "MANAGED_ACQUISITION" });
    mocked.list.mockResolvedValue([{ submissionRef: "opaque", state: "REGISTERED", submission: old }]);
    const response = await POST(request(body) as never, context);
    expect(response.status).toBe(200);
    expect(mocked.register).toHaveBeenCalledTimes(1);
  });
  it.each([
    { workOrderId: "other" }, { siteId: "foreign" }, { cycleNumber: 2 }, { workOrderVersion: 3 },
  ])("rejects a crossed or stale external context %j", async (changed) => {
    mocked.externalContext.mockResolvedValue({ workOrderId: "work-1", siteId: "trusted-site", expectedEpochId: "epoch-1", cycleNumber: 1, workOrderVersion: 2, executionMode: "MANAGED_ACQUISITION", ...changed });
    const response = await POST(request(body) as never, context);
    expect([404, 409]).toContain(response.status);
    expect(mocked.register).not.toHaveBeenCalled();
  });
});
