// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
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
          bounds: [0, 0, 2, 2] }, limitationCodes: ["ACCURACY_UNVERIFIED"] },
    } };
}
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });
beforeEach(() => { Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true }); });

beforeAll(() => {
  // jsdom 의 dialog 는 showModal 미지원 — 열림 상태만 흉내낸다.
  HTMLDialogElement.prototype.showModal = function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function (this: HTMLDialogElement) {
    this.removeAttribute("open", );
  };
});

describe("locked task re-verification stays read-only", () => {
  it("rechecks a locked completed task with GET and never POSTs run", async () => {
    const done = completedView();
    const fetch = vi.fn().mockImplementation(async () => new Response(JSON.stringify(done)));
    vi.stubGlobal("fetch", fetch);
    render(<SpatialTaskPanel initialView={done} initialOptions={options} siteName="테스트 현장" areas={[]} canWrite />);
    fireEvent.click(screen.getByRole("button", { name: "같은 분석 다시 확인" }));
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(fetch.mock.calls.every((call) => String(call[0]) === `/api/sites/site-a/spatial-tasks/${taskId}`)).toBe(true);
    expect(fetch.mock.calls.every((call) => (call[1] as { method?: string } | undefined)?.method === "GET")).toBe(true);
  });
});

describe("Core limitation codes are shown, not dropped", () => {
  it("shows the result limitation code beside the numbers", () => {
    render(<SpatialTaskPanel initialView={completedView()} initialOptions={options} siteName="테스트 현장" areas={[]} canWrite />);
    expect(screen.getByText("ACCURACY_UNVERIFIED")).toBeTruthy();
    expect(screen.getByText("독립 정확도 평가는 아직 확인되지 않았습니다. 이 기록은 물량 정확도 보증, 측량 승인 또는 정산 사용 승인을 뜻하지 않습니다.")).toBeTruthy();
  });
  it("shows readiness limitation codes beside the readiness summary", () => {
    const done = completedView();
    const view: SpatialTaskView = { ...done,
      readiness: { contractVersion: "analysis-readiness.v1", siteId: "site-a", workAreaId: "area-a",
        baseline: done.task.selection.inputs!.baseline, current: done.task.selection.inputs!.current,
        suitabilityState: "PROVISIONAL_ACCURACY_UNVERIFIED", blockers: [],
        limitationCodes: ["PROVISIONAL_ACCURACY_UNVERIFIED"],
        checkedAt: "2026-10-27T00:00:00Z", calculationIdentityDigest: null,
        coverageCheck: "REQUIRES_WORKER_VALIDATION" } };
    expect(isTaskView(view, "site-a", taskId)).toBe(true);
    render(<SpatialTaskPanel initialView={view} initialOptions={options} siteName="테스트 현장" areas={[]} canWrite />);
    expect(screen.getByText("PROVISIONAL_ACCURACY_UNVERIFIED")).toBeTruthy();
  });
});

describe("task result binding rejects unvalidated suitability/limitations", () => {
  it("rejects an unknown suitability state", () => {
    const done = completedView();
    done.analysis = { ...done.analysis!, suitabilityState: "BOGUS" as never };
    expect(isTaskView(done, "site-a", taskId)).toBe(false);
  });
  it("rejects a non-list result limitation", () => {
    const done = completedView();
    done.analysis!.result = { ...done.analysis!.result!, limitationCodes: "x" as never };
    expect(isTaskView(done, "site-a", taskId)).toBe(false);
  });
  it("rejects a missing result limitation list", () => {
    const done = completedView();
    const result = { ...done.analysis!.result! } as Record<string, unknown>;
    delete result.limitationCodes;
    done.analysis!.result = result as never;
    expect(isTaskView(done, "site-a", taskId)).toBe(false);
  });
});

describe("disabled save explains what is missing", () => {
  it("tells the user to pick an area before the save is available", () => {
    render(<SpatialTaskPanel initialView={base} initialOptions={options} siteName="테스트 현장" areas={[]} canWrite />);
    const save = screen.getByRole("button", { name: "이 선택으로 계속" });
    expect(save.matches(":disabled")).toBe(true);
    const hint = screen.getByText(/어느 구역인지 선택하면/);
    expect(save.getAttribute("aria-describedby")).toContain(hint.id);
  });
});

describe("header reload never silently drops an unsaved draft", () => {
  it("asks before reloading while dirty and keeps the draft on cancel", async () => {
    const reload = vi.fn();
    Object.defineProperty(window, "location", { value: { ...window.location, reload }, writable: true, configurable: true });
    vi.stubGlobal("fetch", vi.fn());
    render(<SpatialTaskPanel initialView={base} initialOptions={options} siteName="테스트 현장" areas={[]} canWrite />);
    fireEvent.click(screen.getByLabelText("동측 구역"));
    fireEvent.click(screen.getByRole("button", { name: "저장된 선택 불러오기" }));
    expect(await screen.findByRole("dialog", { name: "저장하지 않은 변경이 있습니다" })).toBeTruthy();
    expect(reload).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "취소" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "저장하지 않은 변경이 있습니다" })).toBeNull());
    expect((screen.getByLabelText("동측 구역") as HTMLInputElement).checked).toBe(true);
    expect(reload).not.toHaveBeenCalled();
  });
  it("reloads directly when nothing is unsaved", () => {
    const reload = vi.fn();
    Object.defineProperty(window, "location", { value: { ...window.location, reload }, writable: true, configurable: true });
    vi.stubGlobal("fetch", vi.fn());
    render(<SpatialTaskPanel initialView={base} initialOptions={options} siteName="테스트 현장" areas={[]} canWrite />);
    fireEvent.click(screen.getByRole("button", { name: "저장된 선택 불러오기" }));
    expect(reload).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog", { name: "저장하지 않은 변경이 있습니다" })).toBeNull();
  });
});

describe("compact viewports stay honest about the notebook-only save", () => {
  it("warns writers up front that saving needs notebook width", () => {
    render(<SpatialTaskPanel initialView={base} initialOptions={options} siteName="테스트 현장" areas={[]} canWrite />);
    expect(screen.getByText(/작은 화면에서는 선택을 저장하거나 분석을 요청할 수 없습니다/)).toBeTruthy();
  });
});

describe("fewer than two observations links the existing registration path", () => {
  it("offers the same-area asset registration route without widening the grant", () => {
    const single: SpatialTaskOptions = { ...options, observations: options.observations.slice(0, 1) };
    render(<SpatialTaskPanel initialView={base} initialOptions={single} siteName="테스트 현장" areas={[]} canWrite />);
    fireEvent.click(screen.getByLabelText("동측 구역"));
    expect(screen.getByText(/두 개 미만입니다/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "등록 자료와 검사 상태 확인" }).getAttribute("href"))
      .toBe("/sites/site-a/spatial-assets?workAreaId=area-a");
  });
});
