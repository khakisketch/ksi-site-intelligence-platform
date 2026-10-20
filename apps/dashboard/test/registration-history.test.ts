import { describe, expect, it } from "vitest";

import {
  validateRegistrationHistory,
  type RegistrationHistoryBindings,
} from "@/lib/registration-history";

const bindings: RegistrationHistoryBindings = {
  submissionRef: `ers-v1-${"b".repeat(64)}`,
  revision: 2,
  siteId: "site-1",
  organizationId: "org-1",
  observationEpochId: "epoch-1",
};

function v3Submission(overrides: Record<string, unknown> = {}) {
  return {
    contractVersion: "external-reconstruction-submission.v3",
    submissionId: "sub-1",
    revision: 2,
    organizationId: "org-1",
    siteId: "site-1",
    observationEpochId: "epoch-1",
    submittedAt: "2026-09-30T01:00:00Z",
    submittedBy: "operator-1",
    executionResponsibility: "customer_operator",
    executionLocus: "customer_workstation",
    producerDeclaration: {
      producerKnowledge: "UNKNOWN",
      softwareName: null,
      softwareVersion: null,
      buildIdentifier: null,
      producerRunIdentifier: null,
      configurationDigest: null,
      completedAt: null,
      sourceNote: null,
    },
    inputDeclaration: {
      rawMediaStoredByKsi: false,
      originalRetentionLocus: "unknown",
      originalRetentionDetail: null,
      localInputManifestDigest: null,
      imageCount: null,
      captureStartedAt: null,
      captureEndedAt: null,
      captureDate: "2021-06-15",
      captureBasis: "DATE_ONLY",
      upstreamSource: {
        sourceUri: "https://example.test/floreat-2021",
        sourceSha256: "d".repeat(64),
        licenceDeclaration: "CC BY 4.0",
        retrievalNote: null,
      },
      derivativeExport: {
        toolName: "KSI Export",
        toolVersion: "1.0",
        settingsDigest: null,
        exportedAt: null,
        exportNote: null,
      },
    },
    artifacts: [],
    ...overrides,
  };
}

function record(submission: unknown, overrides: Record<string, unknown> = {}) {
  return {
    submissionRef: bindings.submissionRef,
    submission,
    state: "REGISTERED",
    manifest: null,
    ...overrides,
  };
}

describe("validateRegistrationHistory", () => {
  it("accepts a V3 record with matching bindings and date-only capture", () => {
    const result = validateRegistrationHistory(record(v3Submission()), bindings);

    expect(result.kind).toBe("v3");
    if (result.kind !== "v3") return;
    expect(result.history.captureBasis).toBe("DATE_ONLY");
    expect(result.history.captureDate).toBe("2021-06-15");
    expect(result.history.producerKnowledge).toBe("UNKNOWN");
    expect(result.history.upstreamSource?.licenceDeclaration).toBe("CC BY 4.0");
    expect(result.history.upstreamSource?.sourceUri).toBe("https://example.test/floreat-2021");
    expect(result.history.derivativeExport?.toolName).toBe("KSI Export");
  });

  it("retains actual Core microseconds and UTC offsets instead of requiring whole-second UI timestamps", () => {
    const original = v3Submission().inputDeclaration;
    const exportedAt = "2026-10-20T23:45:12.123456+09:00";
    const result = validateRegistrationHistory(record(v3Submission({
      inputDeclaration: { ...original, derivativeExport: { ...original.derivativeExport, exportedAt } },
    })), bindings);
    expect(result.kind).toBe("v3");
    if (result.kind === "v3") expect(result.history.derivativeExport?.exportedAt).toBe(exportedAt);
  });

  it("preserves a positive microsecond interval accepted by Core without millisecond rounding", () => {
    const input = v3Submission().inputDeclaration;
    const result = validateRegistrationHistory(record(v3Submission({
      inputDeclaration: { ...input, captureBasis: "EXACT_INTERVAL", captureDate: null,
        captureStartedAt: "2026-10-20T00:00:00.000001Z", captureEndedAt: "2026-10-20T00:00:00.000002Z" },
    })), bindings);
    expect(result.kind).toBe("v3");
  });

  it("refuses internally inconsistent unknown and date-only declarations", () => {
    const original = v3Submission();
    expect(validateRegistrationHistory(record(v3Submission({
      producerDeclaration: { ...original.producerDeclaration, softwareName: "GDAL" },
    })), bindings)).toEqual({ kind: "unavailable" });
    expect(validateRegistrationHistory(record(v3Submission({
      inputDeclaration: { ...original.inputDeclaration, captureDate: null },
    })), bindings)).toEqual({ kind: "unavailable" });
  });

  it("leaves V1 records on the old semantics without new output", () => {
    const v1 = { ...v3Submission(), contractVersion: "external-reconstruction-submission.v1" };
    expect(validateRegistrationHistory(record(v1), bindings)).toEqual({ kind: "legacy" });
  });

  it.each([
    ["revision", { revision: 3 }],
    ["siteId", { siteId: "site-9" }],
    ["organizationId", { organizationId: "org-9" }],
    ["observationEpochId", { observationEpochId: "epoch-9" }],
  ])("refuses a submission binding mismatch without rendering the foreign record: %s", (_label, override) => {
    const submission = v3Submission(override);
    const result = validateRegistrationHistory(record(submission, { state: "SEALED" }), bindings);
    expect(result).toEqual({ kind: "unavailable" });
  });

  it("refuses a record address mismatch without rendering the foreign record", () => {
    const foreign = record(v3Submission(), { submissionRef: `ers-v1-${"c".repeat(64)}` });
    expect(validateRegistrationHistory(foreign, bindings)).toEqual({ kind: "unavailable" });
  });

  it("refuses a cross-organization record without leaking its source", () => {
    const submission = v3Submission({ organizationId: "org-9" });
    const result = validateRegistrationHistory(record(submission), bindings);
    expect(result).toEqual({ kind: "unavailable" });
  });

  it("rejects malformed shapes instead of rendering guesses", () => {
    expect(validateRegistrationHistory(null, bindings)).toEqual({ kind: "unavailable" });
    expect(validateRegistrationHistory(record(null), bindings)).toEqual({ kind: "unavailable" });
    expect(validateRegistrationHistory(record({ ...v3Submission(), revision: "2" }), bindings)).toEqual({ kind: "unavailable" });
    expect(validateRegistrationHistory(
      record(v3Submission({ inputDeclaration: { ...v3Submission().inputDeclaration as object, captureBasis: "SOMETIME" } })),
      bindings,
    )).toEqual({ kind: "unavailable" });
  });

  it("drops an unsafe source URI but keeps the declared licence text", () => {
    const input = v3Submission().inputDeclaration as unknown as Record<string, unknown>;
    const submission = v3Submission({
      inputDeclaration: {
        ...input,
        upstreamSource: { sourceUri: "javascript:alert(1)", sourceSha256: null, licenceDeclaration: "CC BY 4.0", retrievalNote: null },
      },
    });
    const result = validateRegistrationHistory(record(submission), bindings);
    expect(result.kind).toBe("v3");
    if (result.kind !== "v3") return;
    expect(result.history.upstreamSource?.sourceUri).toBeNull();
    expect(result.history.upstreamSource?.licenceDeclaration).toBe("CC BY 4.0");
  });

  it("requires an explicit tool identity for the derivative export", () => {
    const input = v3Submission().inputDeclaration as unknown as Record<string, unknown>;
    const submission = v3Submission({
      inputDeclaration: { ...input, derivativeExport: { toolName: "unknown", toolVersion: "1.0", settingsDigest: null, exportedAt: null, exportNote: null } },
    });
    expect(validateRegistrationHistory(record(submission), bindings)).toEqual({ kind: "unavailable" });
  });
});
