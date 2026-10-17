import { describe, expect, it } from "vitest";

import {
  analysisEvidenceKindLabel,
  analysisEvidenceReasonLine,
  analysisEvidenceSummary,
  analysisObservationLabel,
  getAnalysisIssueGuidance,
} from "@/lib/analysis-guidance";
import type { AnalysisEvidenceItem, AnalysisObservationOption } from "@/lib/core-api/analysis";

const observation: AnalysisObservationOption = {
  selector: {
    workOrderId: "work-order-a",
    submissionRef: `ers-v1-${"a".repeat(64)}`,
    revision: 2,
  },
  observationEpochId: "epoch-recorded-a",
  captureStartedAt: "2026-09-01T00:00:00Z",
  captureEndedAt: "2026-09-01T00:30:00Z",
};

describe("analysis UI guidance", () => {
  it("distinguishes observation choices with their recorded capture interval, revision and existing epoch ID", () => {
    const label = analysisObservationLabel(observation);

    expect(label).toContain("2026. 9. 1.");
    expect(label).toContain("09:00–09:30");
    expect(label).toContain("등록 버전 2");
    expect(label).not.toContain("revision");
    expect(label).toContain("epoch-recorded-a");
  });

  it("maps a known blocker to a human next step without encouraging an identical retry", () => {
    const guidance = getAnalysisIssueGuidance("REASSESSMENT_REQUIRED");

    expect(guidance.label).toBe("현장 적합성 재평가 필요");
    expect(guidance.owner).toContain("담당자");
    expect(guidance.nextStep).toContain("반복 요청하지 마세요");
    expect(guidance.destination).toBeUndefined();
  });

  it("does not guess an unknown reason and keeps the exact code as a separate technical line", () => {
    const code = "NEW_CORE_REASON_FROM_FUTURE";
    const guidance = getAnalysisIssueGuidance(code);

    expect(guidance.label).toBe("세부 원인 확인 필요");
    expect(guidance.nextStep).toContain("화면 안내가 없습니다");
    expect(guidance.nextStep).toContain("반복 요청하지 마세요");
    expect(guidance.label).not.toContain(code);
    expect(analysisEvidenceReasonLine(code)).toContain(`Core 코드 ${code}`);
  });

  it.each(["__proto__", "constructor", "toString"])("does not treat inherited property %s as known guidance", (code) => {
    expect(getAnalysisIssueGuidance(code).label).toBe("세부 원인 확인 필요");
    expect(analysisEvidenceReasonLine(code)).toBe(`세부 원인 확인 필요 · Core 코드 ${code}`);
    expect(analysisEvidenceKindLabel(code)).toBe("추가 근거 기록");
  });

  it("summarizes evidence in task language while retaining its technical identity on expansion", () => {
    const item: AnalysisEvidenceItem = {
      kind: "LIMITATION",
      recordId: "limitation-record-1",
      digest: `sha256:${"b".repeat(64)}`,
      limitationCodes: [],
      source: "BLOCKER",
      code: "NEW_CORE_REASON_FROM_FUTURE",
      epoch: null,
      evidenceRef: null,
      detail: null,
    };

    expect(analysisEvidenceKindLabel(item.kind)).toBe("사용 제한");
    expect(analysisEvidenceSummary(item)).toBe("사용 제한 · 세부 원인 확인 필요");
    expect(analysisEvidenceReasonLine(item.code)).toBe("세부 원인 확인 필요 · Core 코드 NEW_CORE_REASON_FROM_FUTURE");
  });

  it("summarizes evidence rows in business language without row-level codes", () => {
    const epoch: AnalysisEvidenceItem = {
      kind: "EPOCH_IDENTITY",
      recordId: "epoch-record-1",
      digest: `sha256:${"c".repeat(64)}`,
      limitationCodes: [],
      epoch: "BASELINE",
      selector: {
        workOrderId: "work-order-a",
        submissionRef: `ers-v1-${"a".repeat(64)}`,
        revision: 2,
      },
      observationEpochId: "epoch-recorded-a",
      artifactId: "dsm",
      observedSha256: "d".repeat(64),
      observedSizeBytes: 1024,
      observedCrsIdentifier: "EPSG:5186",
      observedCrsDigest: `sha256:${"e".repeat(64)}`,
      verticalReferenceIdentifier: "identifier",
      verticalReferenceBasis: "basis",
      verticalUnit: "metre",
      transform: [1, 0, 0, 0, 1, 0],
      transformDigest: `sha256:${"f".repeat(64)}`,
      inspectionReportDigest: `sha256:${"1".repeat(64)}`,
      inspectionReportRecordId: "report-record-1",
      inputDigest: `sha256:${"2".repeat(64)}`,
    };
    expect(analysisEvidenceSummary(epoch)).toBe("기준 관측 · 지표면 높이 자료(DSM)");
    expect(analysisEvidenceSummary(epoch)).not.toContain("epoch-recorded-a");
    expect(analysisEvidenceSummary(epoch)).not.toContain("ers-v1-");
    expect(analysisEvidenceSummary(epoch)).not.toContain("revision");
    expect(analysisEvidenceSummary(epoch)).not.toContain("등록 버전");

    const evaluation: AnalysisEvidenceItem = {
      kind: "EVALUATION",
      recordId: "evaluation-record-1",
      digest: `sha256:${"3".repeat(64)}`,
      limitationCodes: [],
      evaluationId: "evaluation-1",
      epoch: "CURRENT",
      revision: 3,
      evaluationDigest: `sha256:${"4".repeat(64)}`,
      outcome: "PASS",
      reasonCodes: [],
      assessedAt: "2026-10-09T05:00:00Z",
    };
    expect(analysisEvidenceSummary(evaluation)).toBe("현재 관측 평가 · 통과");

    const checkpoint: AnalysisEvidenceItem = {
      kind: "CHECKPOINT_FACT",
      recordId: "checkpoint-record-1",
      digest: `sha256:${"5".repeat(64)}`,
      limitationCodes: [],
      evaluationId: "evaluation-1",
      epoch: "BASELINE",
      evaluationRevision: 1,
      evidenceRef: "evidence-ref-1",
      contextId: "context-1",
      contextDigest: `sha256:${"6".repeat(64)}`,
      evidenceManifestDigest: `sha256:${"7".repeat(64)}`,
      evidenceRecordId: "record-1",
      evidenceRecordDigest: `sha256:${"8".repeat(64)}`,
      coreVerdict: "VALIDATED",
    };
    expect(analysisEvidenceSummary(checkpoint)).toBe("검사점 근거 · 검증됨");
    expect(analysisEvidenceSummary(checkpoint)).not.toContain("Core");

    expect(analysisEvidenceKindLabel("AUTHORITY_REFERENCE")).toBe("분석 기준 기록");
    expect(analysisEvidenceSummary({ kind: "AUTHORITY_REFERENCE", recordId: "authority-1", digest: `sha256:${"9".repeat(64)}`, limitationCodes: [], referenceName: "admissionId", sourceDigest: null })).toBe("분석 기준 기록 연결");
  });
});
