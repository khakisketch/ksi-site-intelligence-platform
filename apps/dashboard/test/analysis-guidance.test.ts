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
    expect(label).toContain("revision 2");
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
});
