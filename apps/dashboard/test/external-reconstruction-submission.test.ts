import { describe, expect, it } from "vitest";

import {
  canonicalSubmissionDigest,
  type ExternalSubmissionCandidate,
  assertUtf8SafeString,
  validateExternalSubmissionCandidate,
} from "@/lib/external-reconstruction-submission";

const hex = (value: string) => value.repeat(64);

const candidate = (): ExternalSubmissionCandidate => ({
  contractVersion: "external-reconstruction-submission.v1" as const,
  submissionId: "attempt-1",
  revision: 1 as const,
  organizationId: "org-1",
  siteId: "site-1",
  observationEpochId: "epoch-1",
  submittedAt: "2026-09-08T01:02:03Z",
  submittedBy: "operator-1",
  executionResponsibility: "customer_operator" as const,
  executionLocus: "customer_workstation" as const,
  producerDeclaration: {
    softwareName: "KSI 운영 콘솔", softwareVersion: "1.0.0", buildIdentifier: null,
    producerRunIdentifier: null, configurationDigest: null, completedAt: null,
  },
  inputDeclaration: {
    rawMediaStoredByKsi: false as const, originalRetentionLocus: "customer_workstation" as const,
    localInputManifestDigest: null, imageCount: null, captureStartedAt: null, captureEndedAt: null,
  },
  artifacts: [
    { artifactId: "dsm", kind: "dsm" as const, fileName: "surface.tif", format: "GeoTIFF", contentType: "application/octet-stream", declaredSha256: hex("b"), declaredSizeBytes: 2, declaredCrs: null, declaredVerticalReference: null, declaredGsdM: null },
    { artifactId: "ortho", kind: "ortho" as const, fileName: "ortho.tif", format: "GeoTIFF", contentType: "application/octet-stream", declaredSha256: hex("a"), declaredSizeBytes: 1, declaredCrs: null, declaredVerticalReference: null, declaredGsdM: null },
  ],
});

describe("external reconstruction submission canonicalization", () => {
  it("matches the Core Python digest for nullable, Korean, reverse artifact input", () => {
    expect(canonicalSubmissionDigest(candidate())).toBe("sha256:943fcd004843bada56d3c6ebd290d94dd653c8e3c7509989f31fbb525e186db6");
  });
  it("matches the Core Python ORTHO-only golden", () => {
    const orthoOnly = candidate();
    orthoOnly.artifacts = orthoOnly.artifacts.filter((artifact) => artifact.kind === "ortho");
    expect(canonicalSubmissionDigest(orthoOnly)).toBe("sha256:0f842b03c077d76d0e98a7e37d0ba259e552d95d3c564f9ae6834dc6c2249ea7");
  });
  it("rejects an unsafe number and a lone UTF-16 surrogate", () => {
    expect(() => validateExternalSubmissionCandidate({ ...candidate(), revision: Number.MAX_SAFE_INTEGER + 1 as never })).toThrow();
    expect(() => assertUtf8SafeString(String.fromCharCode(0xd800))).toThrow();
  });
});
