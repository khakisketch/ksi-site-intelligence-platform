// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
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

describe("external spatial task selection", () => {
  it("saves only the area, preserving the same task and tells the user how to resume", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ...base,
      task: { ...base.task, revision: 2, selection: { ...base.task.selection, workAreaId: "area-a" } },
      state: "OBSERVATIONS_REQUIRED" }))); vi.stubGlobal("fetch", fetch);
    render(<SpatialTaskPanel initialView={base} initialOptions={options} siteName="테스트 현장" areas={[]} canWrite />);
    fireEvent.click(screen.getByLabelText("동측 구역"));
    fireEvent.click(screen.getByRole("button", { name: "이 선택으로 계속" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("같은 작업"));
    expect(fetch.mock.calls[0][0]).toBe(`/api/sites/site-a/spatial-tasks/${taskId}/selection`);
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ expectedRevision: 1,
      purpose: "OBSERVED_CHANGE", workAreaId: "area-a", inputs: null });
  });

  it("shows unsupported purpose without silently creating observed-change analysis", () => {
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    render(<SpatialTaskPanel initialView={base} initialOptions={options} siteName="테스트 현장" areas={[]} canWrite />);
    fireEvent.change(screen.getByLabelText("무엇을 확인할까요?"), { target: { value: "DAILY_TARGET" } });
    expect(screen.getByText(/계획·기한·작업 여건/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "두 관측 변화 분석 요청" })).toBeNull();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("keeps unsaved choice on conflict and offers saved-selection reload", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ code: "SPATIAL_TASK_REVISION_CONFLICT" }), { status: 409 })));
    render(<SpatialTaskPanel initialView={base} initialOptions={options} siteName="테스트 현장" areas={[]} canWrite />);
    fireEvent.click(screen.getByLabelText("동측 구역"));
    fireEvent.click(screen.getByRole("button", { name: "이 선택으로 계속" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("다른 화면"));
    expect((screen.getByLabelText("동측 구역") as HTMLInputElement).checked).toBe(true);
    expect(screen.getByRole("button", { name: "저장된 선택 불러오기" })).toBeTruthy();
  });

  it("requires paired observation choices without losing the selected area", async () => {
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    render(<SpatialTaskPanel initialView={base} initialOptions={options} siteName="테스트 현장" areas={[]} canWrite />);
    fireEvent.click(screen.getByLabelText("동측 구역"));
    const previous = screen.getByLabelText("이전 관측") as HTMLSelectElement;
    fireEvent.change(previous, { target: { value: previous.options[1].value } });
    fireEvent.click(screen.getByRole("button", { name: "이 선택으로 계속" }));
    expect(screen.getByRole("alert").textContent).toContain("함께 선택");
    expect(document.activeElement).toBe(screen.getByLabelText("이후 관측"));
    expect(fetch).not.toHaveBeenCalled();
  });

  it("does not expose mutation actions to a read-only human", () => {
    render(<SpatialTaskPanel initialView={base} initialOptions={options} siteName="테스트 현장" areas={[]} canWrite={false} />);
    expect(screen.queryByRole("button", { name: "이 선택으로 계속" })).toBeNull();
    expect(screen.getByLabelText("동측 구역").matches(":disabled")).toBe(true);
  });

  it("shows the exact Core result beside the retained map context, with limitations", () => {
    render(<SpatialTaskPanel initialView={completedView()} initialOptions={options} siteName="테스트 현장" areas={[]} canWrite />);
    expect(screen.getByText("5 m³")).toBeTruthy(); expect(screen.getByText("7 m³")).toBeTruthy();
    expect(screen.getByText("2 m³")).toBeTruthy();
    expect(screen.getByText(/설계 잔여량·오늘 작업 목표를 뜻하지/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "분석 기록·근거 자세히" }).getAttribute("href")).toBe("/sites/site-a/analysis?analysisId=analysis-a");
  });

  it("never replaces a failed or unavailable result with zero quantities", () => {
    const failed = completedView(); failed.analysis = { ...failed.analysis!, executionState: "FAILED", result: null };
    render(<SpatialTaskPanel initialView={failed} initialOptions={options} siteName="테스트 현장" areas={[]} canWrite />);
    expect(screen.getByRole("heading", { name: "분석을 완료하지 못했습니다" })).toBeTruthy();
    expect(screen.getByText(/0으로 해석하지 마세요/)).toBeTruthy();
    expect(screen.queryByText(/m³/)).toBeNull();
  });

  it("follows the same pending task by GET until the Core result arrives, with no second run mutation", async () => {
    vi.useFakeTimers();
    const completed = completedView();
    const pending = { ...completed, analysis: { ...completed.analysis!, executionState: "QUEUED" as const, result: null } };
    const fetch = vi.fn(async () => new Response(JSON.stringify(completed))); vi.stubGlobal("fetch", fetch);
    render(<SpatialTaskPanel initialView={pending} initialOptions={options} siteName="테스트 현장" areas={[]} canWrite />);
    expect(screen.getByRole("heading", { name: "분석을 기다리고 있습니다" })).toBeTruthy();
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(screen.getByRole("heading", { name: "두 관측 사이 지형 변화" })).toBeTruthy();
    expect(screen.getByText("5 m³")).toBeTruthy();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledWith(`/api/sites/site-a/spatial-tasks/${taskId}`, expect.objectContaining({ cache: "no-store", method: "GET" }));
    await act(async () => { await vi.advanceTimersByTimeAsync(30000); });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("withholds the pending task when access is lost instead of keeping private controls or stale result links", async () => {
    vi.useFakeTimers();
    const completed = completedView();
    const pending = { ...completed, analysis: { ...completed.analysis!, executionState: "RUNNING" as const, result: null } };
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 403 })));
    render(<SpatialTaskPanel initialView={pending} initialOptions={options} siteName="테스트 현장" areas={[]} canWrite />);
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(screen.getByRole("alert").textContent).toMatch(/권한/);
    expect(screen.queryByRole("link", { name: "분석 기록·근거 자세히" })).toBeNull();
    expect(screen.queryByRole("button", { name: "같은 분석 다시 확인" })).toBeNull();
  });

  it("does not attach an analysis/result change returned under another task", async () => {
    vi.useFakeTimers();
    const completed = completedView();
    const pending = { ...completed, analysis: { ...completed.analysis!, executionState: "RUNNING" as const, result: null } };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ...completed,
      task: { ...completed.task, taskId: `st-${"b".repeat(32)}` } }))));
    render(<SpatialTaskPanel initialView={pending} initialOptions={options} siteName="테스트 현장" areas={[]} canWrite />);
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(screen.queryByText("5 m³")).toBeNull();
    expect(screen.getByRole("alert").textContent).toMatch(/진행 상태/);
  });

  it("pauses after repeated read failures and resumes only read-only following on request", async () => {
    vi.useFakeTimers();
    const completed = completedView();
    const pending = { ...completed, analysis: { ...completed.analysis!, executionState: "RUNNING" as const, result: null } };
    const fetch = vi.fn().mockImplementation(async () => new Response("{}", { status: 503 })); vi.stubGlobal("fetch", fetch);
    render(<SpatialTaskPanel initialView={pending} initialOptions={options} siteName="테스트 현장" areas={[]} canWrite />);
    await act(async () => { await vi.advanceTimersByTimeAsync(9000); });
    expect(screen.getByRole("button", { name: "진행 상태 다시 확인" })).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toMatch(/계산 실패를 뜻하지 않습니다/);
    await act(async () => { await vi.advanceTimersByTimeAsync(30000); });
    expect(fetch).toHaveBeenCalledTimes(3);
    fetch.mockImplementation(async () => new Response(JSON.stringify(completed)));
    fireEvent.click(screen.getByRole("button", { name: "진행 상태 다시 확인" }));
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(screen.getByText("5 m³")).toBeTruthy();
    expect(fetch.mock.calls.every((call) => (call[1] as { method?: string } | undefined)?.method === "GET")).toBe(true);
  });

  describe("same-task resume on return", () => {
    it("reloads the same completed task on return without a second run mutation", async () => {
      const done = completedView();
      const updated: SpatialTaskView = { ...done, task: { ...done.task, revision: 2 },
        analysis: { ...done.analysis!, result: { ...done.analysis!.result!,
          metrics: { cutM3: 9, fillM3: 7, netM3: -2, thresholdM: 0, uncertaintyM3: null } } } };
      const fetch = vi.fn(async (...args: unknown[]) => { void args; return new Response(JSON.stringify(updated)); });
      vi.stubGlobal("fetch", fetch);
      Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
      render(<SpatialTaskPanel initialView={done} initialOptions={options} siteName="테스트 현장" areas={[]} canWrite />);
      expect(screen.getByText("5 m³")).toBeTruthy();
      await act(async () => { window.dispatchEvent(new Event("focus")); });
      await waitFor(() => expect(screen.getByText("9 m³")).toBeTruthy());
      expect(fetch).toHaveBeenCalledTimes(1);
      expect(fetch.mock.calls[0]?.[0]).toBe(`/api/sites/site-a/spatial-tasks/${taskId}`);
      expect(fetch.mock.calls.every((call) => (call[1] as { method?: string } | undefined)?.method === "GET")).toBe(true);
      expect(screen.getByText(/최신 상태를 불러왔습니다/)).toBeTruthy();
    });

    it("invalidates a completed result when the same task reports failure on return", async () => {
      const done = completedView();
      const failed: SpatialTaskView = { ...done, task: { ...done.task, revision: 2 },
        analysis: { ...done.analysis!, executionState: "FAILED", result: null } };
      vi.stubGlobal("fetch", vi.fn(async (...args: unknown[]) => { void args; return new Response(JSON.stringify(failed)); }));
      Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
      render(<SpatialTaskPanel initialView={done} initialOptions={options} siteName="테스트 현장" areas={[]} canWrite />);
      expect(screen.getByText("5 m³")).toBeTruthy();
      await act(async () => { window.dispatchEvent(new Event("focus")); });
      await waitFor(() => expect(screen.getByRole("heading", { name: "분석을 완료하지 못했습니다" })).toBeTruthy());
      expect(screen.queryByText(/m³/)).toBeNull();
      expect(screen.getByText(/0으로 해석하지 마세요/)).toBeTruthy();
    });

    it("preserves an unsaved draft when the same task changes externally", async () => {
      const changed: SpatialTaskView = { ...base, state: "OBSERVATIONS_REQUIRED",
        task: { ...base.task, revision: 2, selection: { purpose: "OBSERVED_CHANGE", workAreaId: "area-a", inputs: null } } };
      const fetch = vi.fn(async (...args: unknown[]) => { void args; return new Response(JSON.stringify(changed)); });
      vi.stubGlobal("fetch", fetch);
      Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
      render(<SpatialTaskPanel initialView={base} initialOptions={options} siteName="테스트 현장" areas={[]} canWrite />);
      fireEvent.click(screen.getByLabelText("동측 구역"));
      await act(async () => { window.dispatchEvent(new Event("focus")); });
      await waitFor(() => expect(screen.getByText(/현재 편집은 유지/)).toBeTruthy());
      expect((screen.getByLabelText("동측 구역") as HTMLInputElement).checked).toBe(true);
      expect(fetch.mock.calls.every((call) => (call[1] as { method?: string } | undefined)?.method === "GET")).toBe(true);
      expect(screen.getByRole("button", { name: "저장된 선택 불러오기" })).toBeTruthy();
    });

    it("withholds the task when access is lost on return instead of keeping stale results", async () => {
      const done = completedView();
      vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 410 })));
      Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
      render(<SpatialTaskPanel initialView={done} initialOptions={options} siteName="테스트 현장" areas={[]} canWrite />);
      expect(screen.getByText("5 m³")).toBeTruthy();
      await act(async () => { window.dispatchEvent(new Event("focus")); });
      await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/만료|새 요청/));
      expect(screen.queryByText("5 m³")).toBeNull();
      expect(screen.queryByRole("link", { name: "분석 기록·근거 자세히" })).toBeNull();
    });

    it("skips background refresh while hidden and resumes when visible", async () => {
      const done = completedView();
      const updated: SpatialTaskView = { ...done, task: { ...done.task, revision: 2 },
        analysis: { ...done.analysis!, result: { ...done.analysis!.result!,
          metrics: { cutM3: 9, fillM3: 7, netM3: -2, thresholdM: 0, uncertaintyM3: null } } } };
      const fetch = vi.fn(async (...args: unknown[]) => { void args; return new Response(JSON.stringify(updated)); });
      vi.stubGlobal("fetch", fetch);
      Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
      render(<SpatialTaskPanel initialView={done} initialOptions={options} siteName="테스트 현장" areas={[]} canWrite />);
      await act(async () => { window.dispatchEvent(new Event("focus")); });
      expect(fetch).not.toHaveBeenCalled();
      Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
      await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
      await waitFor(() => expect(screen.getByText("9 m³")).toBeTruthy());
      expect(fetch.mock.calls.every((call) => (call[1] as { method?: string } | undefined)?.method === "GET")).toBe(true);
    });

    it("ignores a resume payload from another task without clearing the current result", async () => {
      const done = completedView();
      vi.stubGlobal("fetch", vi.fn(async (...args: unknown[]) => { void args; return new Response(JSON.stringify({ ...done,
        task: { ...done.task, taskId: `st-${"b".repeat(32)}` } })); }));
      Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
      render(<SpatialTaskPanel initialView={done} initialOptions={options} siteName="테스트 현장" areas={[]} canWrite />);
      await act(async () => { window.dispatchEvent(new Event("focus")); await new Promise((resolve) => setTimeout(resolve, 0)); });
      expect(screen.getByText("5 m³")).toBeTruthy();
      expect(screen.getByText(/최신 상태를 확인하지 못했습니다/)).toBeTruthy();
      expect(screen.queryByText(/최신 상태를 불러왔습니다/)).toBeNull();
      expect(screen.queryByText(/진행 상태를 다시 확인/)).toBeNull();
    });

    it("does not roll back a newer accepted save with an older in-flight resume response", async () => {
      Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
      const saved: SpatialTaskView = { ...base, state: "OBSERVATIONS_REQUIRED",
        task: { ...base.task, revision: 2, selection: { purpose: "OBSERVED_CHANGE", workAreaId: "area-a", inputs: null } } };
      let resolveOld!: (value: Response) => void;
      const oldGate = new Promise<Response>((resolve) => { resolveOld = resolve; });
      const fetch = vi.fn(async (...args: unknown[]) => {
        const url = args[0] as string;
        const init = args[1] as { method?: string } | undefined;
        if (url.endsWith("/selection") && init?.method === "POST") {
          return new Response(JSON.stringify(saved));
        }
        return oldGate;
      });
      vi.stubGlobal("fetch", fetch);
      render(<SpatialTaskPanel initialView={base} initialOptions={options} siteName="테스트 현장" areas={[]} canWrite />);
      await act(async () => { window.dispatchEvent(new Event("focus")); });
      fireEvent.click(screen.getByLabelText("동측 구역"));
      fireEvent.click(screen.getByRole("button", { name: "이 선택으로 계속" }));
      await waitFor(() => expect(screen.getByText(/선택을 저장했습니다/)).toBeTruthy());
      expect((screen.getByLabelText("동측 구역") as HTMLInputElement).checked).toBe(true);
      await act(async () => { resolveOld(new Response(JSON.stringify(base))); });
      await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
      expect((screen.getByLabelText("동측 구역") as HTMLInputElement).checked).toBe(true);
      expect(screen.getByText(/선택을 저장했습니다/)).toBeTruthy();
      expect(screen.queryByText(/최신 상태를 불러왔습니다/)).toBeNull();
      expect(screen.queryByText(/분석이 완료되었습니다/)).toBeNull();
    });

    it("makes failed freshness explicit without implying the cached result is current", async () => {
      const done = completedView();
      const fetch = vi.fn(async (...args: unknown[]) => { void args; return new Response("{}", { status: 503 }); });
      vi.stubGlobal("fetch", fetch);
      Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
      render(<SpatialTaskPanel initialView={done} initialOptions={options} siteName="테스트 현장" areas={[]} canWrite />);
      expect(screen.getByText("5 m³")).toBeTruthy();
      const focusedBefore = document.activeElement;
      await act(async () => { window.dispatchEvent(new Event("focus")); });
      await waitFor(() => expect(screen.getByText(/최신 상태를 확인하지 못했습니다/)).toBeTruthy());
      expect(screen.getByText("5 m³")).toBeTruthy();
      expect(screen.queryByText(/최신 상태를 불러왔습니다/)).toBeNull();
      expect(document.activeElement).toBe(focusedBefore);
      expect(fetch.mock.calls.every((call) => (call[1] as { method?: string } | undefined)?.method === "GET")).toBe(true);
      const updated: SpatialTaskView = { ...done, task: { ...done.task, revision: 2 },
        analysis: { ...done.analysis!, result: { ...done.analysis!.result!,
          metrics: { cutM3: 9, fillM3: 7, netM3: -2, thresholdM: 0, uncertaintyM3: null } } } };
      fetch.mockImplementation(async (...args: unknown[]) => { void args; return new Response(JSON.stringify(updated)); });
      fireEvent.click(screen.getAllByRole("button", { name: "최신 상태 다시 확인" })[0]);
      await waitFor(() => expect(screen.getByText("9 m³")).toBeTruthy());
      expect(screen.queryByText(/최신 상태를 확인하지 못했습니다/)).toBeNull();
      expect(fetch.mock.calls.every((call) => (call[1] as { method?: string } | undefined)?.method === "GET")).toBe(true);
    });

    it("marks the cached result region itself as not freshly verified", async () => {
      const done = completedView();
      const fetch = vi.fn(async (...args: unknown[]) => { void args; return new Response("{}", { status: 503 }); });
      vi.stubGlobal("fetch", fetch);
      Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
      render(<SpatialTaskPanel initialView={done} initialOptions={options} siteName="테스트 현장" areas={[]} canWrite />);
      await act(async () => { window.dispatchEvent(new Event("focus")); });
      const region = screen.getByRole("region", { name: "같은 구역의 분석 결과" });
      await waitFor(() => expect(within(region).getByText(/새로 확인되지 않았습니다/)).toBeTruthy());
      expect(within(region).getByText("5 m³")).toBeTruthy();
      expect(within(region).getByRole("button", { name: "최신 상태 다시 확인" })).toBeTruthy();
      const updated: SpatialTaskView = { ...done, task: { ...done.task, revision: 2 },
        analysis: { ...done.analysis!, result: { ...done.analysis!.result!,
          metrics: { cutM3: 9, fillM3: 7, netM3: -2, thresholdM: 0, uncertaintyM3: null } } } };
      fetch.mockImplementation(async (...args: unknown[]) => { void args; return new Response(JSON.stringify(updated)); });
      fireEvent.click(within(region).getByRole("button", { name: "최신 상태 다시 확인" }));
      await waitFor(() => expect(screen.getByText("9 m³")).toBeTruthy());
      expect(within(screen.getByRole("region", { name: "같은 구역의 분석 결과" })).queryByText(/새로 확인되지 않았습니다/)).toBeNull();
      expect(fetch.mock.calls.every((call) => (call[1] as { method?: string } | undefined)?.method === "GET")).toBe(true);
    });

    it("marks freshness failed when the resume read times out", async () => {
      vi.useFakeTimers();
      try {
        const done = completedView();
        const fetch = vi.fn(async (...args: unknown[]) => {
          const init = args[1] as { signal?: AbortSignal } | undefined;
          await new Promise<void>((_resolve, reject) => {
            init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
          });
          return new Response(JSON.stringify(done));
        });
        vi.stubGlobal("fetch", fetch);
        Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
        render(<SpatialTaskPanel initialView={done} initialOptions={options} siteName="테스트 현장" areas={[]} canWrite />);
        await act(async () => { window.dispatchEvent(new Event("focus")); });
        await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
        expect(screen.getByText(/최신 상태를 확인하지 못했습니다/)).toBeTruthy();
        expect(screen.getByText("5 m³")).toBeTruthy();
        expect(fetch.mock.calls.every((call) => (call[1] as { method?: string } | undefined)?.method === "GET")).toBe(true);
      } finally {
        vi.useRealTimers();
      }
    });

    it("ignores a late resume response after unmount without errors", async () => {
      const done = completedView();
      let resolveLate!: (value: Response) => void;
      const gate = new Promise<Response>((resolve) => { resolveLate = resolve; });
      const updated: SpatialTaskView = { ...done, task: { ...done.task, revision: 2 } };
      const fetch = vi.fn(async (...args: unknown[]) => { void args; return gate; });
      vi.stubGlobal("fetch", fetch);
      Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
      const view = render(<SpatialTaskPanel initialView={done} initialOptions={options} siteName="테스트 현장" areas={[]} canWrite />);
      await act(async () => { window.dispatchEvent(new Event("focus")); });
      expect(fetch).toHaveBeenCalledTimes(1);
      view.unmount();
      await act(async () => { resolveLate(new Response(JSON.stringify(updated))); });
      await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
      expect(fetch).toHaveBeenCalledTimes(1);
    });
    it("makes a failed resume read explicit without dropping the cached result", async () => {
      const done = completedView();
      vi.stubGlobal("fetch", vi.fn(async (...args: unknown[]) => { void args; throw new Error("연결 끊김"); }));
      Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
      render(<SpatialTaskPanel initialView={done} initialOptions={options} siteName="테스트 현장" areas={[]} canWrite />);
      await act(async () => { window.dispatchEvent(new Event("focus")); });
      await waitFor(() => expect(screen.getByText(/최신 상태를 확인하지 못했습니다/)).toBeTruthy());
      expect(screen.getByText("5 m³")).toBeTruthy();
      expect(screen.getAllByText(/새 계산을 요청하지 않았습니다/)).toHaveLength(2);
    });
  });
});

describe("task result binding before display", () => {
  it("accepts the bound Core result and rejects a different area", () => {
    const done = completedView();
    expect(isTaskView(done, "site-a", taskId)).toBe(true);
    done.analysis = { ...done.analysis!, workAreaId: "different-area" };
    expect(isTaskView(done, "site-a", taskId)).toBe(false);
  });
  it("rejects nonfinite or non-completed numeric projections", () => {
    const done = completedView(); done.analysis!.result!.metrics.cutM3 = NaN;
    expect(isTaskView(done, "site-a", taskId)).toBe(false);
    const queued = completedView(); queued.analysis!.executionState = "QUEUED";
    expect(isTaskView(queued, "site-a", taskId)).toBe(false);
  });
});
