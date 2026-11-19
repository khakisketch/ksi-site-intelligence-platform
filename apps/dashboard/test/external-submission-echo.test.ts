import { describe, expect, it } from "vitest";

import { declarationEchoOfRequest, isRevisionViewForAttempt, sameInstant, type AttemptEcho, type V3DeclarationBody } from "@/lib/external-submission-echo";

const body: V3DeclarationBody = {
  submissionId: "submission-1",
  expectedEpochId: "epoch-1",
  submittedAt: "2026-11-19T00:00:00Z",
  producerKnowledge: "UNKNOWN",
  softwareName: null,
  softwareVersion: null,
  sourceNote: null,
  captureBasis: "UNKNOWN",
  captureStartedAt: null,
  captureEndedAt: null,
  captureDate: null,
  originalRetentionLocus: "unknown",
  originalRetentionDetail: null,
  upstreamSource: null,
  derivativeExport: null,
  artifacts: [{
    artifactId: "dsm",
    kind: "dsm",
    fileName: "surface.tif",
    format: "GeoTIFF",
    contentType: "application/octet-stream",
    declaredSha256: "a".repeat(64),
    declaredSizeBytes: 1,
    declaredCrs: null,
    declaredVerticalReference: null,
    declaredGsdM: null,
  }],
};

describe("V3 declaration response binding", () => {
  it("compares the complete registered instant across timezone spellings", () => {
    const start = "2024-07-05T12:30:45.456004+09:00";
    expect(sameInstant(start, "2024-07-05T03:30:45.456004Z")).toBe(true);
    expect(sameInstant(start, "2024-07-05T03:30:45.456005Z")).toBe(false);
    expect(sameInstant(start, "2024-07-05T03:30:45.456Z")).toBe(false);
  });

  it("keeps the ordinary intake echo on the first revision without a preknown ref", () => {
    expect(declarationEchoOfRequest(body)).toMatchObject({ revision: 1, expectedSubmissionRef: null });
  });

  it("binds a correction echo to the exact existing ref and next revision", () => {
    const correction = {
      ...body,
      correctionOf: { submissionRef: `ers-v1-${"a".repeat(64)}`, revision: 4 },
    };
    expect(declarationEchoOfRequest(correction)).toMatchObject({
      revision: 5,
      expectedSubmissionRef: correction.correctionOf.submissionRef,
    });
  });

  it("accepts the corrected stream response and rejects a different opaque ref", () => {
    const correction = {
      ...body,
      correctionOf: { submissionRef: `ers-v1-${"a".repeat(64)}`, revision: 4 },
    };
    const echo: AttemptEcho = { submissionRef: null, ...declarationEchoOfRequest(correction) };
    const submission = {
      contractVersion: "external-reconstruction-submission.v3",
      submissionId: correction.submissionId,
      revision: 5,
      observationEpochId: correction.expectedEpochId,
      submittedAt: correction.submittedAt,
      submissionDigest: `sha256:${"b".repeat(64)}`,
      producerDeclaration: {
        producerKnowledge: correction.producerKnowledge,
        softwareName: correction.softwareName,
        softwareVersion: correction.softwareVersion,
        sourceNote: correction.sourceNote,
      },
      inputDeclaration: {
        captureBasis: correction.captureBasis,
        captureStartedAt: correction.captureStartedAt,
        captureEndedAt: correction.captureEndedAt,
        captureDate: correction.captureDate,
        originalRetentionLocus: correction.originalRetentionLocus,
        originalRetentionDetail: correction.originalRetentionDetail,
        upstreamSource: correction.upstreamSource,
        derivativeExport: correction.derivativeExport,
      },
      artifacts: correction.artifacts,
    };
    const response = {
      submissionRef: correction.correctionOf.submissionRef,
      state: "REGISTERED",
      manifest: null,
      submission,
    };
    expect(isRevisionViewForAttempt(response, echo, "REGISTERED")).toBe(true);
    expect(isRevisionViewForAttempt({ ...response, submissionRef: `ers-v1-${"c".repeat(64)}` }, echo, "REGISTERED")).toBe(false);
  });
});
