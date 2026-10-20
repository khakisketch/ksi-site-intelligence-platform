import { describe, expect, it } from "vitest";

import {
  canonicalSubmissionDigest,
  canonicalSubmissionV3Digest,
  describeV3MetadataIssue,
  isPublisherCalendarDate,
  seoulDateTimeLocalToUtc,
  sealExternalSubmissionV3,
  validateExternalSubmissionV3Candidate,
  type ExternalSubmissionCandidate,
  type ExternalSubmissionCandidateV3,
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
  it("matches the Core Python golden when a header-read CRS is declared", () => {
    const declared = candidate();
    declared.artifacts = declared.artifacts.map((artifact) => ({ ...artifact, declaredCrs: "EPSG:5186" }));
    expect(canonicalSubmissionDigest(declared)).toBe("sha256:e9239da2c843b54b27a5a28cb6f894ff5951fae5a9d95219e5102fef62bdb8c2");
  });
  it("rejects an unsafe number and a lone UTF-16 surrogate", () => {
    expect(() => validateExternalSubmissionCandidate({ ...candidate(), revision: Number.MAX_SAFE_INTEGER + 1 as never })).toThrow();
    expect(() => assertUtf8SafeString(String.fromCharCode(0xd800))).toThrow();
  });
  it("converts an explicitly labelled Seoul capture interval to exact UTC and rejects an unordered pair", () => {
    expect(seoulDateTimeLocalToUtc("2026-09-06T09:10")).toBe("2026-09-06T00:10:00Z");
    expect(seoulDateTimeLocalToUtc("2026-02-30T09:10")).toBeNull();
    const unordered = candidate();
    unordered.inputDeclaration.captureStartedAt = "2026-09-06T00:10:00Z";
    unordered.inputDeclaration.captureEndedAt = "2026-09-06T00:00:00Z";
    expect(() => validateExternalSubmissionCandidate(unordered)).toThrow();
  });
});

describe("external reconstruction V3 missing-info intake", () => {
  const v3ExactBoth = (): ExternalSubmissionCandidateV3 => ({
    contractVersion: "external-reconstruction-submission.v3" as const,
    submissionId: "attempt-v3-1",
    revision: 1 as const,
    organizationId: "org-1",
    siteId: "site-1",
    observationEpochId: "epoch-1",
    submittedAt: "2026-10-09T01:02:03Z",
    submittedBy: "operator-1",
    executionResponsibility: "customer_operator" as const,
    executionLocus: "customer_workstation" as const,
    producerDeclaration: {
      producerKnowledge: "DECLARED" as const, softwareName: "DJI Terra", softwareVersion: "4.1.0",
      buildIdentifier: null, producerRunIdentifier: null, configurationDigest: null, completedAt: null, sourceNote: null,
    },
    inputDeclaration: {
      rawMediaStoredByKsi: false as const, originalRetentionLocus: "customer_workstation" as const,
      originalRetentionDetail: null, localInputManifestDigest: null, imageCount: null,
      captureStartedAt: "2026-10-08T00:00:00Z", captureEndedAt: "2026-10-08T01:00:00Z",
      captureDate: null, captureBasis: "EXACT_INTERVAL" as const, upstreamSource: null, derivativeExport: null,
    },
    artifacts: [
      { artifactId: "dsm" as const, kind: "dsm" as const, fileName: "surface.tif", format: "GeoTIFF", contentType: "application/octet-stream", declaredSha256: hex("b"), declaredSizeBytes: 2, declaredCrs: null, declaredVerticalReference: null, declaredGsdM: null },
      { artifactId: "ortho" as const, kind: "ortho" as const, fileName: "ortho.tif", format: "GeoTIFF", contentType: "application/octet-stream", declaredSha256: hex("a"), declaredSizeBytes: 1, declaredCrs: "EPSG:5186", declaredVerticalReference: null, declaredGsdM: null },
    ],
  });

  const v3DateOnlyUnknown = (): ExternalSubmissionCandidateV3 => ({
    contractVersion: "external-reconstruction-submission.v3" as const,
    submissionId: "attempt-v3-2",
    revision: 1 as const,
    organizationId: "org-1",
    siteId: "site-1",
    observationEpochId: "epoch-1",
    submittedAt: "2026-10-09T01:02:03Z",
    submittedBy: "operator-1",
    executionResponsibility: "customer_operator" as const,
    executionLocus: "customer_workstation" as const,
    producerDeclaration: {
      producerKnowledge: "UNKNOWN" as const, softwareName: null, softwareVersion: null,
      buildIdentifier: null, producerRunIdentifier: null, configurationDigest: null, completedAt: null, sourceNote: null,
    },
    inputDeclaration: {
      rawMediaStoredByKsi: false as const, originalRetentionLocus: "upstream_source" as const,
      originalRetentionDetail: "portal keeps originals", localInputManifestDigest: null, imageCount: null,
      captureStartedAt: null, captureEndedAt: null,
      captureDate: "2026-10-08", captureBasis: "DATE_ONLY" as const,
      upstreamSource: {
        sourceUri: "https://example.invalid/source/ortho.tif",
        sourceSha256: hex("c"), licenceDeclaration: "publisher page states open reuse", retrievalNote: "exported 2026-10-08",
      },
      derivativeExport: {
        toolName: "GDAL", toolVersion: "3.8.0",
        settingsDigest: `sha256:${hex("d")}`, exportedAt: "2026-10-08T02:00:00Z", exportNote: "reproject to EPSG:5186",
      },
    },
    artifacts: [
      { artifactId: "dsm" as const, kind: "dsm" as const, fileName: "surface.tif", format: "GeoTIFF", contentType: "application/octet-stream", declaredSha256: hex("b"), declaredSizeBytes: 2, declaredCrs: "EPSG:5186", declaredVerticalReference: null, declaredGsdM: null },
    ],
  });

  it("matches the Core Python V3 digest for an exact declared interval with both artifacts", () => {
    expect(canonicalSubmissionV3Digest(v3ExactBoth())).toBe("sha256:af19326e6129f09ef8a48b0ba9c7919daf04c090aee4216ff1347a813eb74e33");
  });

  it("matches the Core Python V3 digest for a date-only unknown-producer DSM-only declaration", () => {
    expect(canonicalSubmissionV3Digest(v3DateOnlyUnknown())).toBe("sha256:7b8178828e4103bb7a719aa0b0144fcbea0a50a1d5bd74ccb133124f886b0c13");
  });

  it("seals a V3 candidate with the same digest the wire parser revalidates", () => {
    const sealed = sealExternalSubmissionV3(v3DateOnlyUnknown());
    expect(sealed.submissionDigest).toBe(canonicalSubmissionV3Digest(v3DateOnlyUnknown()));
    expect(validateExternalSubmissionV3Candidate(sealed)).toBeUndefined();
  });

  it("keeps DATE_ONLY timestamps null in the canonical payload instead of inventing midnight", () => {
    const payload = JSON.parse(JSON.stringify(v3DateOnlyUnknown())) as Record<string, Record<string, unknown>>;
    expect(payload.inputDeclaration.captureStartedAt).toBeNull();
    expect(payload.inputDeclaration.captureEndedAt).toBeNull();
    expect(payload.inputDeclaration.captureDate).toBe("2026-10-08");
    expect(JSON.stringify(payload)).not.toContain("T00:00:00");
  });

  it("accepts DSM-only and ortho-only packages while refusing an empty or kind-less package", () => {
    expect(() => validateExternalSubmissionV3Candidate(v3DateOnlyUnknown())).not.toThrow();
    const orthoOnly = v3ExactBoth();
    orthoOnly.artifacts = orthoOnly.artifacts.filter((artifact) => artifact.kind === "ortho");
    expect(() => validateExternalSubmissionV3Candidate(orthoOnly)).not.toThrow();
    const empty = v3DateOnlyUnknown();
    empty.artifacts = [];
    expect(() => validateExternalSubmissionV3Candidate(empty)).toThrow();
    const foreign = v3DateOnlyUnknown();
    foreign.artifacts = [{ ...foreign.artifacts[0]!, kind: "point_cloud" as never }];
    expect(() => validateExternalSubmissionV3Candidate(foreign)).toThrow();
    const duplicate = v3ExactBoth();
    duplicate.artifacts = [duplicate.artifacts[0]!, duplicate.artifacts[0]!];
    expect(() => validateExternalSubmissionV3Candidate(duplicate)).toThrow();
  });

  it("rejects mixed capture metadata before any HTTP", () => {
    const dateWithTime = v3DateOnlyUnknown();
    dateWithTime.inputDeclaration.captureStartedAt = "2026-10-08T00:00:00Z";
    expect(() => validateExternalSubmissionV3Candidate(dateWithTime)).toThrow();
    const exactWithDate = v3ExactBoth();
    exactWithDate.inputDeclaration.captureDate = "2026-10-08";
    expect(() => validateExternalSubmissionV3Candidate(exactWithDate)).toThrow();
    const unknownWithDate = v3DateOnlyUnknown();
    unknownWithDate.inputDeclaration.captureBasis = "UNKNOWN";
    expect(() => validateExternalSubmissionV3Candidate(unknownWithDate)).toThrow();
    const equalInterval = v3ExactBoth();
    equalInterval.inputDeclaration.captureEndedAt = equalInterval.inputDeclaration.captureStartedAt;
    expect(() => validateExternalSubmissionV3Candidate(equalInterval)).toThrow();
  });

  it("rejects the fabricated literal unknown and mismatched producer presence", () => {
    for (const [knowledge, name, version] of [
      ["DECLARED", "unknown", "1"], ["DECLARED", "ODM", "unknown"], ["DECLARED", "ODM", "UNKNOWN"],
      ["PARTIAL", "unknown", null], ["PARTIAL", "ODM", "1"], ["PARTIAL", null, null],
      ["UNKNOWN", "ODM", null], ["UNKNOWN", null, "1"],
    ] as const) {
      const broken = v3ExactBoth();
      broken.producerDeclaration = {
        producerKnowledge: knowledge, softwareName: name, softwareVersion: version,
        buildIdentifier: null, producerRunIdentifier: null, configurationDigest: null, completedAt: null, sourceNote: null,
      };
      expect(() => validateExternalSubmissionV3Candidate(broken)).toThrow();
    }
    const partial = v3ExactBoth();
    partial.producerDeclaration = {
      producerKnowledge: "PARTIAL", softwareName: "DJI Terra", softwareVersion: null,
      buildIdentifier: null, producerRunIdentifier: null, configurationDigest: null, completedAt: null, sourceNote: null,
    };
    expect(() => validateExternalSubmissionV3Candidate(partial)).not.toThrow();
  });

  it("rejects unsafe upstream references, bad digests, and naive export times", () => {
    for (const uri of ["ftp://example.invalid/x.tif", "https://user@example.invalid/x", "https://example.invalid/has space", "javascript:alert(1)", "example.invalid/no-scheme"]) {
      const broken = v3DateOnlyUnknown();
      broken.inputDeclaration.upstreamSource = { sourceUri: uri, sourceSha256: null, licenceDeclaration: null, retrievalNote: null };
      expect(() => validateExternalSubmissionV3Candidate(broken)).toThrow();
    }
    const badSha = v3DateOnlyUnknown();
    badSha.inputDeclaration.upstreamSource = { ...badSha.inputDeclaration.upstreamSource!, sourceSha256: "xyz" };
    expect(() => validateExternalSubmissionV3Candidate(badSha)).toThrow();
    const badDigest = v3DateOnlyUnknown();
    badDigest.inputDeclaration.derivativeExport = { ...badDigest.inputDeclaration.derivativeExport!, settingsDigest: "abc" };
    expect(() => validateExternalSubmissionV3Candidate(badDigest)).toThrow();
    const naiveExport = v3DateOnlyUnknown();
    naiveExport.inputDeclaration.derivativeExport = { ...naiveExport.inputDeclaration.derivativeExport!, exportedAt: "2026-10-08T02:00:00" };
    expect(() => validateExternalSubmissionV3Candidate(naiveExport)).toThrow();
    const rawStored = v3DateOnlyUnknown();
    rawStored.inputDeclaration.rawMediaStoredByKsi = true as never;
    expect(() => validateExternalSubmissionV3Candidate(rawStored)).toThrow();
  });

  it("validates the publisher calendar date without timezone conversion", () => {
    expect(isPublisherCalendarDate("2026-10-08")).toBe(true);
    expect(isPublisherCalendarDate("2026-02-30")).toBe(false);
    expect(isPublisherCalendarDate("2026-10-08T00:00:00Z")).toBe(false);
    expect(isPublisherCalendarDate("")).toBe(false);
    expect(isPublisherCalendarDate(null)).toBe(false);
  });

  it("guides the console form away from fabricated or mixed metadata", () => {
    const blank = {
      producerKnowledge: "DECLARED" as const, softwareName: "", softwareVersion: "", sourceNote: "",
      captureBasis: "UNKNOWN" as const, captureDateLocal: "", upstreamUri: "", upstreamSha: "",
      exportToolName: "", exportToolVersion: "", exportSettingsDigest: "", exportedAtLocal: "", exportNote: "",
    };
    expect(describeV3MetadataIssue(blank)).toMatch(/이름과 버전/);
    expect(describeV3MetadataIssue({ ...blank, softwareName: "unknown", softwareVersion: "1" })).toMatch(/'unknown'/);
    expect(describeV3MetadataIssue({ ...blank, producerKnowledge: "UNKNOWN", softwareName: "ODM" })).toMatch(/비워 두세요/);
    expect(describeV3MetadataIssue({ ...blank, producerKnowledge: "PARTIAL", softwareName: "ODM", softwareVersion: "1" })).toMatch(/버전을 비워/);
    expect(describeV3MetadataIssue({ ...blank, softwareName: "ODM", softwareVersion: "1", captureBasis: "DATE_ONLY", captureDateLocal: "2021-13-40" })).toMatch(/YYYY-MM-DD/);
    expect(describeV3MetadataIssue({ ...blank, softwareName: "ODM", softwareVersion: "1", upstreamUri: "ftp://example.invalid/x" })).toMatch(/http\(s\)/);
    expect(describeV3MetadataIssue({ ...blank, softwareName: "ODM", softwareVersion: "1" })).toBeNull();
  });
});
