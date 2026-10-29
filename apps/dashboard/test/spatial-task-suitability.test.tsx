// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SpatialTaskPanel } from "@/app/sites/[siteId]/spatial-tasks/[taskId]/SpatialTaskPanel";
import { isTaskView, type SpatialTaskOptions, type SpatialTaskView } from "@/lib/spatial-task";

vi.mock("@/components/map/WorkAreaChoiceMap", () => ({ WorkAreaChoiceMap: () => <div>등록된 지도 경계</div> }));
const taskId = `st-${"a".repeat(32)}`;
const base: SpatialTaskView = {
  task: { taskId, siteId: "site-a", revision: 1,
    selection: { purpose: "OBSERVED_CHANGE", workAreaId: null, inputs: null },
    analysisId: null, executionRequested: false, createdAt: "2026-10-27T00:00:00Z", expiresAt: "2026-11-03T00:00:00Z" },
  state: "AREA_REQUIRED", selectionHref: `/sites/site-a/spatial-tasks/${taskId}`, analysisHref: null,
  readiness: null, analysis: null,
};
const options: SpatialTaskOptions = {
  siteId: "site-a", areas: [{ workAreaId: "area-a", name: "동측 구역" }], nextOffset: null,
  observations: ["a", "b"].map((letter, index) => ({
    selector: { workOrderId: `order-${letter}`, submissionRef: `ers-v1-${letter.repeat(64)}`, revision: 1 },
    observationEpochId: `epoch-${letter}`, captureStartedAt: `2026-10-${20 + index}T00:00:00Z`,
    captureEndedAt: `2026-10-${20 + index}T01:00:00Z`, workAreaIds: ["area-a"],
  })),
};
function completedView(): SpatialTaskView {
  const inputs = { baseline: options.observations[0].selector, current: options.observations[1].selector };
  return { ...base, state: "ANALYSIS_LINKED", task: { ...base.task,
    selection: { purpose: "OBSERVED_CHANGE", workAreaId: "area-a", inputs },
    executionRequested: true, analysisId: "analysis-a" },
    analysis: { analysisId: "analysis-a", siteId: "site-a", workAreaId: "area-a", ...inputs,
      executionState: "COMPLETED", suitabilityState: "PROVISIONAL_ACCURACY_UNVERIFIED", blockers: [],
      evidenceRevision: 1, evidenceDigest: `sha256:${"a".repeat(64)}`, evidenceHref: "/v2/evidence",
      coverageHref: "/v2/coverage", createdAt: base.task.createdAt,
      result: { resultId: "result-a", reportDigest: `sha256:${"a".repeat(64)}`,
        numericResultIdentityDigest: `sha256:${"b".repeat(64)}`, computedAt: base.task.createdAt,
        metrics: { cutM3: 5, fillM3: 7, netM3: 2, thresholdM: 0, uncertaintyM3: null },
        coverage: { coverageWitnessDigest: `sha256:${"c".repeat(64)}`, rows: 2, columns: 2,
          selectedCellCount: 4, commonValidCellCount: 4, unavailableCellCount: 0,
          thresholdExcludedCellCount: 0, cellAreaM2: 1, selectedAreaM2: 4, commonValidAreaM2: 4,
          bounds: [0, 0, 2, 2] }, limitationCodes: [] },
    } };
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
beforeEach(() => { Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true }); });

describe("numeric result binding matches the Core contract", () => {
  it("accepts numbers only on COMPLETED provisional/evaluated suitability", () => {
    const provisional = completedView();
    expect(isTaskView(provisional, "site-a", taskId)).toBe(true);
    const evaluated = completedView();
    evaluated.analysis = { ...evaluated.analysis!, suitabilityState: "EVALUATED" };
    expect(isTaskView(evaluated, "site-a", taskId)).toBe(true);
  });
  it("rejects numbers on withholding suitability even when execution completed", () => {
    for (const suitability of ["BLOCKED", "REMEDIATION_REQUIRED", "REASSESSMENT_REQUIRED"] as const) {
      const view = completedView();
      view.analysis = { ...view.analysis!, suitabilityState: suitability };
      expect(isTaskView(view, "site-a", taskId)).toBe(false);
    }
  });
  it("rejects a completed analysis without numbers unless the state explains the limitation", () => {
    for (const suitability of ["PROVISIONAL_ACCURACY_UNVERIFIED", "EVALUATED"] as const) {
      const view = completedView();
      view.analysis = { ...view.analysis!, suitabilityState: suitability, result: null };
      expect(isTaskView(view, "site-a", taskId)).toBe(false);
    }
    for (const suitability of ["BLOCKED", "REMEDIATION_REQUIRED", "REASSESSMENT_REQUIRED"] as const) {
      const view = completedView();
      view.analysis = { ...view.analysis!, suitabilityState: suitability, result: null,
        blockers: [{ code: suitability === "BLOCKED" ? "ESSENTIAL_INPUT_UNAVAILABLE" : suitability, epoch: null, evidenceRef: null, detail: null }] };
      expect(isTaskView(view, "site-a", taskId)).toBe(true);
    }
  });
  it("still accepts pending and failed views without numbers", () => {
    const queued = completedView();
    queued.analysis = { ...queued.analysis!, executionState: "QUEUED", result: null };
    expect(isTaskView(queued, "site-a", taskId)).toBe(true);
    const failed = completedView();
    failed.analysis = { ...failed.analysis!, executionState: "FAILED", suitabilityState: "BLOCKED", result: null,
      blockers: [{ code: "EMPTY_COMMON_VALID_COVERAGE", epoch: null, evidenceRef: null, detail: null }] };
    expect(isTaskView(failed, "site-a", taskId)).toBe(true);
  });
});

describe("suitability copy never claims an absent evaluation", () => {
  it("states the independent evaluation basis on EVALUATED without an unverified claim", () => {
    const view = completedView();
    view.analysis = { ...view.analysis!, suitabilityState: "EVALUATED" };
    render(<SpatialTaskPanel initialView={view} initialOptions={options} siteName="테스트 현장" areas={[]} canWrite />);
    expect(screen.getByText(/독립 평가 근거가 있습니다/)).toBeTruthy();
    expect(screen.queryByText(/아직 확인되지 않았습니다/)).toBeNull();
    expect(screen.getByText("5 m³")).toBeTruthy();
  });
  it("withholds historical numbers on completed reassessment and names the reason", () => {
    const view = completedView();
    view.analysis = { ...view.analysis!, suitabilityState: "REASSESSMENT_REQUIRED", result: null,
      blockers: [{ code: "REASSESSMENT_REQUIRED", epoch: null, evidenceRef: null, detail: null }] };
    render(<SpatialTaskPanel initialView={view} initialOptions={options} siteName="테스트 현장" areas={[]} canWrite />);
    expect(screen.getByText(/완료된 계산이 있으나 현재 적합성이 확인되지 않아 수치를 제공하지 않습니다/)).toBeTruthy();
    expect(screen.getByText(/현장 적합성 재평가 필요/)).toBeTruthy();
    expect(screen.queryByText(/m³/)).toBeNull();
    expect(screen.queryByText(/아직 확인되지 않았습니다/)).toBeNull();
  });
  it("keeps the provisional wording only for genuinely provisional results", () => {
    render(<SpatialTaskPanel initialView={completedView()} initialOptions={options} siteName="테스트 현장" areas={[]} canWrite />);
    expect(screen.getByText(/독립 정확도 평가는 아직 확인되지 않았습니다/)).toBeTruthy();
    expect(screen.queryByText(/독립 평가 근거가 있습니다/)).toBeNull();
  });
});
