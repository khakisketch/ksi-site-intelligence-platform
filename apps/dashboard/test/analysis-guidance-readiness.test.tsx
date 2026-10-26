import { describe, expect, it } from "vitest";

import { getAnalysisIssueGuidance } from "@/lib/analysis-guidance";

const READINESS_CODES = [
  "READINESS_DSM_UNAVAILABLE",
  "READINESS_CAPTURE_INTERVAL_UNAVAILABLE",
  "READINESS_INSPECTION_PENDING",
  "READINESS_INSPECTION_REJECTED",
  "READINESS_INSPECTION_BINDING_INVALID",
  "READINESS_VERTICAL_REFERENCE_UNAVAILABLE",
  "READINESS_VERTICAL_UNIT_UNAVAILABLE",
  "READINESS_PROJECTED_UNIT_UNAVAILABLE",
  "READINESS_BASELINE_GRID_INVALID",
];

describe("readiness blocker guidance", () => {
  it.each(READINESS_CODES)("maps %s to precise Korean guidance with an owner and next step", (code) => {
    const guidance = getAnalysisIssueGuidance(code);
    // 원문 코드 폴백이 아니라 이 코드의 안내다.
    expect(guidance.label).not.toBe("세부 원인 확인 필요");
    expect(guidance.owner.length).toBeGreaterThan(0);
    expect(guidance.nextStep.length).toBeGreaterThan(0);
    expect(guidance.destination).toBe("spatial-assets");
    // 기술 코드는 펼침에만 두므로 1차 문구에 원문 코드가 섞이지 않는다.
    expect(guidance.label).not.toContain("READINESS");
    expect(guidance.nextStep).not.toContain("READINESS");
  });

  it("tells waiting apart from terminal", () => {
    expect(getAnalysisIssueGuidance("READINESS_INSPECTION_PENDING").nextStep).toMatch(/기다리면 해결될 수/);
    for (const code of READINESS_CODES.filter((item) => item !== "READINESS_INSPECTION_PENDING")) {
      const guidance = getAnalysisIssueGuidance(code);
      // 기다린다고 해결되지 않으며, 취할 행동(직접 또는 담당자 확인)이 있다.
      expect(guidance.nextStep).not.toMatch(/기다리면 해결될 수/);
      expect(`${guidance.nextStep} ${guidance.selfServiceNextStep ?? ""}`).toMatch(/보완|다시 등록|다시 export|다른 .* 고르|같은 결과|확인하세요/);
    }
    expect(getAnalysisIssueGuidance("READINESS_INSPECTION_REJECTED").nextStep).toMatch(/거부|다시 등록|보완/);
  });

  it("names per-epoch precise causes without inventing metadata", () => {
    expect(getAnalysisIssueGuidance("READINESS_CAPTURE_INTERVAL_UNAVAILABLE").nextStep).toMatch(/UTC/);
    expect(getAnalysisIssueGuidance("READINESS_VERTICAL_REFERENCE_UNAVAILABLE").label).toMatch(/수직 기준/);
    expect(getAnalysisIssueGuidance("READINESS_PROJECTED_UNIT_UNAVAILABLE").label).toMatch(/평면/);
    expect(getAnalysisIssueGuidance("READINESS_BASELINE_GRID_INVALID").label).toMatch(/기준 격자/);
    const dsm = getAnalysisIssueGuidance("READINESS_DSM_UNAVAILABLE");
    expect(dsm.nextStep).toMatch(/정확히 1건|DSM/);
    // 추측·수치 주장이 없다.
    expect(JSON.stringify(READINESS_CODES.map((code) => getAnalysisIssueGuidance(code)))).not.toMatch(/정확도 보증|RMSE|절대정확도/);
  });
});
