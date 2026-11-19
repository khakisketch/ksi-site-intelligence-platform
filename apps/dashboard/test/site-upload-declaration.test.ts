import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildSimpleUploadBody, captureWindowIssue, type SimpleUploadFile } from "@/lib/site-upload-declaration";

const mocked = vi.hoisted(() => ({ session: vi.fn(), coreFetchWithToken: vi.fn(), externalContext: vi.fn(), list: vi.fn(), register: vi.fn() }));
vi.mock("@/lib/core-api/session", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/core-api/session")>();
  return { ...actual, getSessionToken: mocked.session };
});
vi.mock("@/lib/core-api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/core-api/client")>();
  return { ...actual, coreFetchWithToken: mocked.coreFetchWithToken };
});
vi.mock("@/lib/core-api/external-reconstruction", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/core-api/external-reconstruction")>();
  return {
    ...actual,
    getExternalReconstructionContextWithToken: mocked.externalContext,
    listExternalReconstructionSubmissionsWithToken: mocked.list,
    registerExternalReconstructionSubmissionV3WithToken: mocked.register,
  };
});
import { POST } from "@/app/api/observation-work-orders/[workOrderId]/external-reconstruction-submissions-v3/route";

const hex = (value: string) => value.repeat(64);
const ortho: SimpleUploadFile = { kind: "ortho", fileName: "북측_orthomosaic.tif", sha256: hex("a"), size: 1_900_000_000, declaredCrs: "EPSG:5186", producer: { name: "Pix4Dmatic", version: "1.67.0" } };
const dsm: SimpleUploadFile = { kind: "dsm", fileName: "북측_DSM.tif", sha256: hex("b"), size: 840_000_000, declaredCrs: "EPSG:5186", producer: null };
const base = { submissionId: "console-1", expectedEpochId: "epoch-1", submittedAt: "2026-11-18T01:30:00Z", startedLocal: "2026-11-18T09:20", endedLocal: "2026-11-18T10:05" };

describe("captureWindowIssue", () => {
  it("accepts a proper past interval", () => {
    expect(captureWindowIssue("2026-11-18T09:20", "2026-11-18T10:05")).toBeNull();
  });
  it("rejects missing, reversed, equal and future ends", () => {
    expect(captureWindowIssue("", "2026-11-18T10:05")).toMatch(/모두 입력/);
    expect(captureWindowIssue("2026-11-18T10:05", "2026-11-18T09:20")).toMatch(/늦어야/);
    expect(captureWindowIssue("2026-11-18T09:20", "2026-11-18T09:20")).toMatch(/늦어야/);
    expect(captureWindowIssue("2026-11-18T09:20", "2999-01-01T00:00")).toMatch(/미래/);
    expect(captureWindowIssue("2026-13-18T09:20", "2026-11-18T10:05")).toMatch(/모두 입력/);
  });
});

describe("buildSimpleUploadBody", () => {
  it("converts KST to UTC and records an exact interval with honest unknowns", () => {
    const built = buildSimpleUploadBody({ ...base, files: [ortho, dsm] });
    expect(built.ok).toBe(true);
    if (!built.ok) return;
    expect(built.body).toMatchObject({
      captureBasis: "EXACT_INTERVAL",
      captureStartedAt: "2026-11-18T00:20:00Z",
      captureEndedAt: "2026-11-18T01:05:00Z",
      captureDate: null,
      originalRetentionLocus: "unknown",
      originalRetentionDetail: null,
      upstreamSource: null,
      derivativeExport: null,
      sourceNote: null,
    });
    expect(built.body.artifacts.map((artifact) => artifact.artifactId)).toEqual(["ortho", "dsm"]);
    expect(built.body.artifacts.every((artifact) => artifact.declaredVerticalReference === null && artifact.declaredGsdM === null)).toBe(true);
  });

  it("derives producer knowledge only from what the header said", () => {
    const named = buildSimpleUploadBody({ ...base, files: [ortho] });
    const partial = buildSimpleUploadBody({ ...base, files: [{ ...ortho, producer: { name: "Metashape", version: null } }] });
    const none = buildSimpleUploadBody({ ...base, files: [dsm] });
    expect(named.ok && named.body).toMatchObject({ producerKnowledge: "DECLARED", softwareName: "Pix4Dmatic", softwareVersion: "1.67.0" });
    expect(partial.ok && partial.body).toMatchObject({ producerKnowledge: "PARTIAL", softwareName: "Metashape", softwareVersion: null });
    expect(none.ok && none.body).toMatchObject({ producerKnowledge: "UNKNOWN", softwareName: null, softwareVersion: null });
  });

  it("declares a producer only when every included artifact agrees on its name and version", () => {
    const missing = { ...dsm, producer: null };
    const matching = { ...dsm, producer: { name: "Pix4Dmatic", version: " 1.67.0 " } };
    const differentName = { ...dsm, producer: { name: "Metashape", version: "1.67.0" } };
    const differentVersion = { ...dsm, producer: { name: "Pix4Dmatic", version: "2.0" } };
    const sameNameUnknownVersion = { ...dsm, producer: { name: "Pix4Dmatic", version: null } };
    const expected = (files: readonly SimpleUploadFile[]) => {
      const result = buildSimpleUploadBody({ ...base, files });
      if (!result.ok) throw new Error(result.reason);
      return result.body;
    };

    expect(expected([ortho, matching])).toMatchObject({
      producerKnowledge: "DECLARED", softwareName: "Pix4Dmatic", softwareVersion: "1.67.0",
    });
    const firstOrder = expected([ortho, matching]);
    const reversedOrder = expected([matching, ortho]);
    expect(firstOrder).toMatchObject({
      producerKnowledge: reversedOrder.producerKnowledge,
      softwareName: reversedOrder.softwareName,
      softwareVersion: reversedOrder.softwareVersion,
    });
    expect(expected([ortho, missing])).toMatchObject({
      producerKnowledge: "UNKNOWN", softwareName: null, softwareVersion: null,
    });
    expect(expected([ortho, differentName])).toMatchObject({
      producerKnowledge: "UNKNOWN", softwareName: null, softwareVersion: null,
    });
    expect(expected([ortho, differentVersion])).toMatchObject({
      producerKnowledge: "PARTIAL", softwareName: "Pix4Dmatic", softwareVersion: null,
    });
    expect(expected([ortho, sameNameUnknownVersion])).toMatchObject({
      producerKnowledge: "PARTIAL", softwareName: "Pix4Dmatic", softwareVersion: null,
    });
  });

  it("refuses bad intervals, empty selections and duplicate kinds", () => {
    expect(buildSimpleUploadBody({ ...base, startedLocal: "", files: [ortho] })).toMatchObject({ ok: false });
    expect(buildSimpleUploadBody({ ...base, files: [] })).toMatchObject({ ok: false });
    expect(buildSimpleUploadBody({ ...base, files: [ortho, { ...ortho, fileName: "again.tif" }] })).toMatchObject({ ok: false });
  });
});

// 실제 V3 등록 BFF가 이 신고서를 그대로 받아 Core 후보를 만드는지 확인한다.
describe("compatibility with the V3 registration BFF", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mocked.session.mockResolvedValue("token");
    mocked.coreFetchWithToken.mockImplementation(async (path: unknown) => {
      if (String(path).endsWith("/v1/auth/whoami")) return { principalId: "trusted-principal", organizationId: "trusted-org" };
      return { workOrderId: "work-1", organizationId: "trusted-org", siteId: "trusted-site", cycleNumber: 1, version: 2, executionMode: "EXTERNAL_RECONSTRUCTION" };
    });
    mocked.externalContext.mockResolvedValue({ workOrderId: "work-1", siteId: "trusted-site", expectedEpochId: "epoch-1", cycleNumber: 1, workOrderVersion: 2, executionMode: "EXTERNAL_RECONSTRUCTION" });
    mocked.list.mockResolvedValue([]);
    mocked.register.mockResolvedValue({ submissionRef: "opaque", state: "REGISTERED" });
  });

  it.each([
    ["ortho and dsm", [ortho, dsm]],
    ["dsm only", [dsm]],
    ["ortho only", [ortho]],
  ])("registers %s with a valid canonical digest", async (_label, files) => {
    const built = buildSimpleUploadBody({ ...base, files });
    if (!built.ok) throw new Error(built.reason);
    const response = await POST(
      new Request("http://console.test/api", { method: "POST", headers: { "content-type": "application/json", host: "console.test" }, body: JSON.stringify(built.body) }) as never,
      { params: Promise.resolve({ workOrderId: "work-1" }) },
    );
    expect(response.status).toBe(201);
    const submitted = mocked.register.mock.calls[0]![1];
    expect(submitted.inputDeclaration.captureBasis).toBe("EXACT_INTERVAL");
    expect(submitted.submissionDigest).toMatch(/^sha256:[0-9a-f]{64}$/);
    expect(submitted.artifacts).toHaveLength(files.length);
  });

  it("registers files with conflicting producer tags without inventing one group producer", async () => {
    const files = [ortho, { ...dsm, producer: { name: "Metashape", version: "2.1" } }];
    const built = buildSimpleUploadBody({ ...base, files });
    if (!built.ok) throw new Error(built.reason);

    const response = await POST(
      new Request("http://console.test/api", { method: "POST", headers: { "content-type": "application/json", host: "console.test" }, body: JSON.stringify(built.body) }) as never,
      { params: Promise.resolve({ workOrderId: "work-1" }) },
    );

    expect(response.status).toBe(201);
    expect(mocked.register.mock.calls[0]![1].producerDeclaration).toMatchObject({
      producerKnowledge: "UNKNOWN", softwareName: null, softwareVersion: null,
    });
    expect(mocked.register.mock.calls[0]![1].submissionDigest).toMatch(/^sha256:[0-9a-f]{64}$/);
  });
});
