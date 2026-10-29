import { describe, expect, it } from "vitest";

import { deriveExternalWorkOrderStage } from "@/app/field/external-work-order-stage";
import type { ExternalResultSummaryView } from "@/lib/core-api/types";

const base = {
  planningOnly: false,
  workflowClosed: false,
  sealedSubmissionCount: 0,
  registeredSubmissionCount: 0,
  latestResult: null,
};

function result(overrides: Partial<ExternalResultSummaryView> = {}): ExternalResultSummaryView {
  return {
    reportRef: "report-1",
    reportDigest: "sha256:a",
    requestRef: "req-1",
    requestDigest: "sha256:b",
    sourceWorkOrderId: "wo-1",
    currentWorkOrderId: "wo-1",
    baselineWorkOrderId: "wo-0",
    decisionId: "d-1",
    decisionDigest: "sha256:c",
    workAreaId: "area-1",
    zoneDefinitionDigest: "sha256:d",
    crs: "EPSG:5186",
    observedCrsDigest: "sha256:e",
    verticalReferenceDigest: "sha256:f",
    baselineCapturedFrom: "2026-09-01T00:00:00Z",
    baselineCapturedTo: "2026-09-01T01:00:00Z",
    currentCapturedFrom: "2026-09-02T00:00:00Z",
    currentCapturedTo: "2026-09-02T01:00:00Z",
    reportedAt: "2026-09-02T02:00:00Z",
    measurementStatus: "SUCCEEDED",
    measurementReason: null,
    metrics: null,
    executionPolicy: {
      policyId: "p",
      version: 1,
      policyDigest: "sha256:g",
      algorithmBuildDigest: "sha256:h",
      configDigest: "sha256:i",
      uncertaintyMethod: "INDEPENDENT_EPOCH_RSS_AREA_BOUND_V1",
    },
    reviewRef: null,
    reviewDigest: null,
    reviewedAt: null,
    proposalCount: 0,
    approvedProposalCount: 0,
    ...overrides,
  } as ExternalResultSummaryView;
}

describe("deriveExternalWorkOrderStage", () => {
  it("asks for registration when nothing is registered", () => {
    expect(deriveExternalWorkOrderStage(base)).toMatchObject({ stage: "REGISTER", label: "외부 산출물 등록 준비" });
  });
  it("asks to seal when a registration is not sealed", () => {
    expect(deriveExternalWorkOrderStage({ ...base, registeredSubmissionCount: 1 })).toMatchObject({ stage: "SEAL", label: "업로드·봉인 필요" });
  });
  it("asks for a comparison decision when sealed but no result", () => {
    expect(deriveExternalWorkOrderStage({ ...base, sealedSubmissionCount: 1 })).toMatchObject({ stage: "DECIDE", label: "검사와 비교 판정" });
  });
  it("asks for review when a result exists without review", () => {
    expect(deriveExternalWorkOrderStage({ ...base, sealedSubmissionCount: 1, latestResult: result() })).toMatchObject({ stage: "REVIEW", label: "결과와 근거 검토" });
  });
  it("asks for a proposal decision after review", () => {
    expect(
      deriveExternalWorkOrderStage({ ...base, sealedSubmissionCount: 1, latestResult: result({ reviewRef: "err-1", reviewedAt: "2026-09-02T03:00:00Z" }) }),
    ).toMatchObject({ stage: "PROPOSE", label: "재관측 필요 여부 결정" });
  });
  it("is done after an approved proposal", () => {
    expect(
      deriveExternalWorkOrderStage({ ...base, sealedSubmissionCount: 1, latestResult: result({ reviewRef: "err-1", approvedProposalCount: 1 }) }),
    ).toMatchObject({ stage: "DONE", label: "후속 관측 계획됨" });
  });
  it("closed wins over everything", () => {
    expect(deriveExternalWorkOrderStage({ ...base, workflowClosed: true, latestResult: result() }).stage).toBe("CLOSED");
  });
  it("labels planning-only successors for registration", () => {
    expect(deriveExternalWorkOrderStage({ ...base, planningOnly: true })).toMatchObject({ stage: "REGISTER", label: "승인된 재관측 산출물 등록" });
  });
});
