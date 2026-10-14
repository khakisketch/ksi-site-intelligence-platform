/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const router = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

import { AnalysisRequestPanel } from "@/app/sites/[siteId]/analysis/AnalysisRequestPanel";
import type { AnalysisEvidencePage, AnalysisListPage, AnalysisObservationOption, AnalysisView } from "@/lib/core-api/analysis";

const selector = (workOrderId: string, digit: string) => ({ workOrderId, submissionRef: `ers-v1-${digit.repeat(64)}`, revision: 1 });
const observations: (AnalysisObservationOption & { workAreaIds: string[] })[] = [
  { selector: selector("work-baseline", "a"), observationEpochId: "epoch-baseline", captureStartedAt: "2026-09-01T00:00:00Z", captureEndedAt: "2026-09-01T00:30:00Z", workAreaIds: ["area-1"] },
  { selector: selector("work-current", "b"), observationEpochId: "epoch-current", captureStartedAt: "2026-09-08T00:00:00Z", captureEndedAt: "2026-09-08T00:30:00Z", workAreaIds: ["area-1"] },
];
const scope = { organizationId: "org-1", principalId: "operator-1" };
const metrics = { cutM3: 12, fillM3: 20, netM3: 8, thresholdM: 0.1, uncertaintyM3: null };
const result = {
  resultId: "result-core-1",
  reportDigest: `sha256:${"1".repeat(64)}`,
  numericResultIdentityDigest: `sha256:${"2".repeat(64)}`,
  computedAt: "2026-09-08T02:00:00Z",
  metrics,
  coverage: {
    coverageWitnessDigest: `sha256:${"3".repeat(64)}`,
    rows: 10,
    columns: 10,
    selectedCellCount: 100,
    commonValidCellCount: 90,
    unavailableCellCount: 10,
    thresholdExcludedCellCount: 2,
    cellAreaM2: 1,
    selectedAreaM2: 100,
    commonValidAreaM2: 90,
    bounds: [0, 0, 10, 10] as [number, number, number, number],
  },
  limitationCodes: ["PROVISIONAL_ACCURACY_UNVERIFIED", "INSPECTION_LIMITED"],
};

function detail(analysisId = "analysis-1", executionState: AnalysisView["executionState"] = "COMPLETED"): AnalysisView {
  return {
    analysisId,
    siteId: "site-1",
    workAreaId: "area-1",
    baseline: observations[0]!.selector,
    current: observations[1]!.selector,
    executionState,
    suitabilityState: "PROVISIONAL_ACCURACY_UNVERIFIED",
    blockers: [],
    result: executionState === "COMPLETED" ? result : null,
    evidenceRevision: 1,
    evidenceDigest: `sha256:${"4".repeat(64)}`,
    evidenceHref: `/v2/sites/site-1/analyses/${analysisId}/evidence`,
    coverageHref: `/v2/sites/site-1/analyses/${analysisId}/coverage`,
    createdAt: "2026-09-08T01:00:00Z",
  };
}

function listItem(analysisId: string) {
  return {
    analysisId,
    siteId: "site-1",
    workAreaId: "area-1",
    executionState: "COMPLETED" as const,
    suitabilityState: "PROVISIONAL_ACCURACY_UNVERIFIED" as const,
    createdAt: "2026-09-08T01:00:00Z",
    resultId: result.resultId,
    metrics,
    limitationCount: result.limitationCodes.length,
    analysisHref: `/v2/sites/site-1/analyses/${analysisId}`,
  };
}

function listPage(items: string[], nextCursor: string | null = null): AnalysisListPage {
  return { siteId: "site-1", items: items.map(listItem), nextCursor };
}

function evidencePage(recordId: string, nextCursor: string | null): AnalysisEvidencePage {
  return {
    analysisId: "analysis-1",
    evidenceRevision: 1,
    evidenceDigest: `sha256:${"5".repeat(64)}`,
    nextCursor,
    items: [{ kind: "LIMITATION", recordId, digest: `sha256:${recordId.padEnd(64, "a")}`, limitationCodes: [], source: "RESULT", code: recordId, epoch: null, evidenceRef: null, detail: `근거 ${recordId}` }],
  };
}

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json" } });
}

function renderPanel(overrides: Partial<Parameters<typeof AnalysisRequestPanel>[0]> = {}) {
  const initial = detail();
  return render(<AnalysisRequestPanel
    siteId="site-1"
    {...scope}
    workAreas={[{ workAreaId: "area-1", name: "1구역" }]}
    observations={observations}
    initialPage={listPage([initial.analysisId])}
    initialSelectedDetail={initial}
    canCreate={false}
    initialAnalysisId={initial.analysisId}
    {...overrides}
  />);
}

afterEach(() => {
  cleanup();
  router.replace.mockReset();
  vi.restoreAllMocks();
  sessionStorage.clear();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("analysis V2 panel", () => {
  it("uses capture time, revision and the recorded epoch ID to distinguish observations", () => {
    renderPanel({ initialPage: listPage([]), initialSelectedDetail: null, initialAnalysisId: null, canCreate: true });

    const baseline = screen.getByLabelText("기준 관측") as HTMLSelectElement;
    const current = screen.getByLabelText("현재 관측") as HTMLSelectElement;
    expect(baseline.value).toBe("");
    expect(current.value).toBe("");
    expect(baseline.disabled).toBe(true);
    expect(screen.getByText("가능한 경우 현재 관측보다 앞서 끝난 가장 최근 관측을 기준으로 제안합니다. 기준은 수정할 수 있고, 분석 요청은 직접 눌러야 합니다.")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("작업구역"), { target: { value: "area-1" } });
    expect(baseline.options[1]?.textContent).toContain("revision 1 · epoch-baseline");
    expect(baseline.options[1]?.textContent).toContain("09:00–09:30");

    fireEvent.change(baseline, { target: { value: "0" } });
    fireEvent.change(current, { target: { value: "1" } });
    expect(screen.getByText(/선택 확인 · 작업구역 연결은 Core가 요청 시 확인합니다/)).toBeTruthy();
    expect(screen.getByText(/기준 · .*revision 1 · epoch-baseline/)).toBeTruthy();
    expect(screen.getByText(/현재 · .*revision 1 · epoch-current/)).toBeTruthy();

    const selectorDetails = screen.getByText("요청 selector 전체 확인").closest("details");
    expect(selectorDetails?.hasAttribute("open")).toBe(false);
    fireEvent.click(screen.getByText("요청 selector 전체 확인"));
    expect(selectorDetails?.textContent).toContain(observations[0]!.selector.submissionRef);
    expect(selectorDetails?.textContent).toContain("work-baseline");
    expect(selectorDetails?.textContent).toContain("revision · 1");
  });

  it("scopes both pickers to the WorkArea and suggests the unique latest prior epoch without submitting", () => {
    const scoped: (AnalysisObservationOption & { workAreaIds: string[] })[] = [
      { ...observations[0]!, selector: selector("work-t0", "a"), observationEpochId: "epoch-t0", captureStartedAt: "2026-09-01T00:00:00Z", captureEndedAt: "2026-09-01T00:30:00Z" },
      { ...observations[0]!, selector: selector("work-t1", "b"), observationEpochId: "epoch-t1", captureStartedAt: "2026-09-08T00:00:00Z", captureEndedAt: "2026-09-08T00:30:00Z" },
      { ...observations[0]!, selector: selector("work-t2", "c"), observationEpochId: "epoch-t2", captureStartedAt: "2026-09-15T00:00:00Z", captureEndedAt: "2026-09-15T00:30:00Z" },
      { ...observations[0]!, selector: selector("other-area", "d"), observationEpochId: "epoch-other-area", captureStartedAt: "2026-09-15T00:00:00Z", captureEndedAt: "2026-09-15T00:30:00Z", workAreaIds: ["area-2"] },
    ];
    renderPanel({ observations: scoped, workAreas: [{ workAreaId: "area-1", name: "1구역" }, { workAreaId: "area-2", name: "2구역" }], initialPage: listPage([]), initialSelectedDetail: null, initialAnalysisId: null, canCreate: true, unattributedObservationCount: 1 });

    fireEvent.change(screen.getByLabelText("작업구역"), { target: { value: "area-1" } });
    const baseline = screen.getByLabelText("기준 관측") as HTMLSelectElement;
    const current = screen.getByLabelText("현재 관측") as HTMLSelectElement;
    expect(baseline.options).toHaveLength(4);
    expect([...baseline.options].map((option) => option.textContent).join(" ")).not.toContain("epoch-other-area");
    fireEvent.change(current, { target: { value: "2" } });
    expect(baseline.value).toBe("1");
    expect(screen.getByText("작업구역 연결을 확인할 수 없는 관측은 선택지에서 제외했습니다.")).toBeTruthy();
    expect([...current.options].map((option) => option.textContent).join(" ")).not.toContain("회차");
    fireEvent.change(baseline, { target: { value: "0" } });
    expect(baseline.value).toBe("0");
  });

  it("does not suggest an overlapping or tied latest prior epoch", () => {
    const overlapping: (AnalysisObservationOption & { workAreaIds: string[] })[] = [
      { ...observations[0]!, selector: selector("work-older", "a"), observationEpochId: "epoch-older", captureStartedAt: "2026-09-01T00:00:00Z", captureEndedAt: "2026-09-01T00:30:00Z" },
      { ...observations[0]!, selector: selector("work-overlap", "b"), observationEpochId: "epoch-overlap", captureStartedAt: "2026-09-08T00:20:00Z", captureEndedAt: "2026-09-11T00:10:00Z" },
      { ...observations[0]!, selector: selector("work-tie", "c"), observationEpochId: "epoch-tie", captureStartedAt: "2026-09-09T00:00:00Z", captureEndedAt: "2026-09-09T00:30:00Z" },
      { ...observations[0]!, selector: selector("work-tie-2", "d"), observationEpochId: "epoch-tie-2", captureStartedAt: "2026-09-09T00:00:00Z", captureEndedAt: "2026-09-09T00:30:00Z" },
      { ...observations[0]!, selector: selector("work-current-later", "e"), observationEpochId: "epoch-current-later", captureStartedAt: "2026-09-11T00:00:00Z", captureEndedAt: "2026-09-11T00:30:00Z" },
    ];
    renderPanel({ observations: overlapping, initialPage: listPage([]), initialSelectedDetail: null, initialAnalysisId: null, canCreate: true });

    fireEvent.change(screen.getByLabelText("작업구역"), { target: { value: "area-1" } });
    fireEvent.change(screen.getByLabelText("현재 관측"), { target: { value: "4" } });
    expect((screen.getByLabelText("기준 관측") as HTMLSelectElement).value).toBe("");
  });

  it("shows safe remediation and preserves the original blocker only in technical details", () => {
    const blocked = {
      ...detail(),
      suitabilityState: "BLOCKED" as const,
      blockers: [{ code: "VERTICAL_REFERENCE_MISMATCH", message: null, epoch: "CURRENT" as const, evidenceRef: "checkpoint-ref-1", detail: "height datum differs" }],
      result: null,
    };
    const page = listPage(["analysis-1"]);
    page.items[0] = { ...page.items[0]!, suitabilityState: "BLOCKED", resultId: null, metrics: null, limitationCount: 1 };

    renderPanel({ initialPage: page, initialSelectedDetail: blocked });
    const selected = within(screen.getByText("분석 analysis-1").closest("article")!);

    expect(selected.getByText("높이 기준이 서로 다름 · 현재 관측")).toBeTruthy();
    expect(selected.getByText(/수직 기준과 단위를 담당자가 확인해야 합니다/)).toBeTruthy();
    expect(selected.getByRole("link", { name: "공간 자산 기록 확인" }).getAttribute("href")).toBe("/sites/site-1/spatial-assets?workAreaId=area-1");
    const technical = selected.getByText("Core 코드·원문 설명 보기").closest("details");
    expect(technical?.hasAttribute("open")).toBe(false);
    fireEvent.click(selected.getByText("Core 코드·원문 설명 보기"));
    expect(technical?.textContent).toContain("VERTICAL_REFERENCE_MISMATCH");
    expect(technical?.textContent).toContain("height datum differs");
    expect(technical?.textContent).toContain("checkpoint-ref-1");
  });

  it("gives an honest fallback for unknown blocker codes without treating them as retryable", () => {
    const blocked = {
      ...detail(),
      suitabilityState: "BLOCKED" as const,
      blockers: [{ code: "FUTURE_REASON_CODE", message: null, epoch: null, evidenceRef: null, detail: null }],
      result: null,
    };
    const page = listPage(["analysis-1"]);
    page.items[0] = { ...page.items[0]!, suitabilityState: "BLOCKED", resultId: null, metrics: null, limitationCount: 1 };

    renderPanel({ initialPage: page, initialSelectedDetail: blocked });
    const selected = within(screen.getByText("분석 analysis-1").closest("article")!);
    expect(selected.getByText("세부 원인 확인 필요")).toBeTruthy();
    expect(selected.getByText(/이 사유에 대한 화면 안내가 없습니다/)).toBeTruthy();
    expect(selected.getByText(/반복 요청하지 마세요/)).toBeTruthy();
    expect(selected.getByText("Core 코드·원문 설명 보기").closest("details")?.hasAttribute("open")).toBe(false);
  });

  it("explains a completed execution with reassessment required without exposing the raw state code", () => {
    const current = {
      ...detail(),
      suitabilityState: "REASSESSMENT_REQUIRED" as const,
      blockers: [{ code: "REASSESSMENT_REQUIRED", message: null, epoch: null, evidenceRef: null, detail: null }],
      result: null,
    };
    const page = listPage(["analysis-1"]);
    page.items[0] = { ...page.items[0]!, suitabilityState: "REASSESSMENT_REQUIRED", resultId: null, metrics: null, limitationCount: 1 };

    renderPanel({ initialPage: page, initialSelectedDetail: current });

    const selected = within(screen.getByText("분석 analysis-1").closest("article")!);
    expect(selected.getByText("실행 완료")).toBeTruthy();
    expect(selected.getByText("재평가 필요")).toBeTruthy();
    expect(selected.getByText("계산은 완료됐습니다. 현장 적합성은 재평가가 필요합니다.")).toBeTruthy();
    expect(selected.getByText("현장 적합성 재평가 필요")).toBeTruthy();
    expect(selected.getByText("Core 코드·원문 설명 보기").closest("details")?.hasAttribute("open")).toBe(false);
  });

  it("retires cached numeric detail when reselecting a completed analysis before refreshed I/O", async () => {
    const other = detail("analysis-2");
    other.result = { ...result, resultId: "other-result" };
    let finish: (value: Response) => void = () => { throw new Error("refresh not started"); };
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(json(detail()))
      .mockResolvedValueOnce(json(other))
      .mockImplementationOnce(() => new Promise<Response>((resolve) => { finish = resolve; })));
    renderPanel({ initialPage: listPage(["analysis-1", "analysis-2"]) });
    await waitFor(() => expect(screen.getByText("result-core-1")).toBeTruthy());
    fireEvent.click(screen.getAllByRole("button", { name: "이 분석 보기" })[1]!);
    await screen.findByText("other-result");
    fireEvent.click(screen.getAllByRole("button", { name: "이 분석 보기" })[0]!);
    const selected = within(screen.getByText("분석 analysis-1").closest("article")!);
    expect(selected.queryByText("result-core-1")).toBeNull();
    expect(selected.queryByText("계산 결과")).toBeNull();
    const current = { ...detail(), suitabilityState: "REASSESSMENT_REQUIRED" as const, result: null };
    finish(json(current));
    await waitFor(() => expect(selected.getByText("재평가 필요")).toBeTruthy());
    expect(selected.queryByText("계산 결과")).toBeNull();
  });

  it("hides numeric detail and summary fallback when current detail refresh fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ code: "UNAVAILABLE" }, 503)));
    renderPanel();
    await screen.findByRole("alert");
    expect(screen.queryByText("result-core-1")).toBeNull();
    expect(screen.queryByText("계산 결과")).toBeNull();
    expect(screen.queryByRole("button", { name: "근거 확인" })).toBeNull();
    expect(screen.getByRole("button", { name: "분석 상세 다시 불러오기" })).toBeTruthy();
  });

  it.each([true, false])("withdraws stale detail and evidence on refreshed remediation even if detail fetch succeeds=%s", async (success) => {
    const current = { ...detail(), suitabilityState: "REASSESSMENT_REQUIRED" as const, result: null,
      evidenceRevision: 2, evidenceDigest: `sha256:${"6".repeat(64)}`,
      blockers: [{ code: "CHECKPOINT_EVALUATION_FAILED", message: null }],
    };
    const page = listPage(["analysis-1"]);
    page.items[0] = { ...page.items[0]!, suitabilityState: "REASSESSMENT_REQUIRED", resultId: null, metrics: null };
    let finishDetail: (response: Response) => void = () => { throw new Error("detail fetch not started"); };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(detail()))
      .mockResolvedValueOnce(json(evidencePage("OLD-EVIDENCE", null)))
      .mockResolvedValueOnce(json(page))
      .mockImplementationOnce(() => new Promise<Response>((resolve) => { finishDetail = resolve; }));
    vi.stubGlobal("fetch", fetchMock);
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: "근거 확인" }));
    await screen.findByText("근거 OLD-EVIDENCE");
    fireEvent.focus(window);
    await waitFor(() => expect(screen.queryByText("result-core-1")).toBeNull());
    expect(screen.queryByText("근거 OLD-EVIDENCE")).toBeNull();
    finishDetail(success ? json(current) : json({ code: "UNAVAILABLE" }, 503));
    if (success) await screen.findByText("CHECKPOINT_EVALUATION_FAILED");
    else await screen.findByRole("alert");
    expect(screen.queryByText("result-core-1")).toBeNull();
  });

  it("shows Core's exact IDs, metrics and limitations from V2 detail", () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(detail())));
    renderPanel();
    expect(screen.getByText("분석 analysis-1")).toBeTruthy();
    expect(screen.getByRole("region", { name: "계산 결과 표" }).getAttribute("tabindex")).toBe("0");
    expect(screen.getByText("result-core-1")).toBeTruthy();
    expect(screen.getByText("정확도 평가 미확인")).toBeTruthy();
    expect(screen.getByText("자료 검사에 제한 있음")).toBeTruthy();
    expect(screen.getByText("정확도 미확인")).toBeTruthy();
  });

  it("freezes a selector-only POST and reuses its idempotency key after an ambiguous response", async () => {
    const created = detail("analysis-created", "QUEUED");
    created.suitabilityState = "PROVISIONAL_ACCURACY_UNVERIFIED";
    created.result = null;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json({ error: "temporary" }, 503))
      .mockResolvedValueOnce(json(created, 202));
    vi.stubGlobal("fetch", fetchMock);
    renderPanel({ initialPage: listPage([]), initialSelectedDetail: null, initialAnalysisId: null, canCreate: true });

    fireEvent.change(screen.getByLabelText("작업구역"), { target: { value: "area-1" } });
    fireEvent.change(screen.getByLabelText("기준 관측"), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText("현재 관측"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "분석 요청" }));
    await screen.findByText("요청을 다시 시도하세요.");
    fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    const [firstUrl, firstInit] = fetchMock.mock.calls[0]!;
    const [secondUrl, secondInit] = fetchMock.mock.calls[1]!;
    expect(firstUrl).toBe("/api/sites/site-1/work-areas/area-1/analyses");
    expect(secondUrl).toBe(firstUrl);
    expect(JSON.parse(firstInit.body)).toEqual({ baseline: observations[0]!.selector, current: observations[1]!.selector });
    expect(secondInit.headers["Idempotency-Key"]).toBe(firstInit.headers["Idempotency-Key"]);
    expect(screen.getByText("분석 analysis-created")).toBeTruthy();
  });

  it.each(["ANALYSIS_ACTIVATION_UNAVAILABLE", "ANALYSIS_ACTIVATION_EXPIRED"])("explains persistent activation failure %s and keeps retry and cancel available", async (code) => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json({ code }, 503))
      .mockResolvedValueOnce(json({ code }, 503));
    vi.stubGlobal("fetch", fetchMock);
    renderPanel({ initialPage: listPage([]), initialSelectedDetail: null, initialAnalysisId: null, canCreate: true });

    fireEvent.change(screen.getByLabelText("작업구역"), { target: { value: "area-1" } });
    fireEvent.change(screen.getByLabelText("기준 관측"), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText("현재 관측"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "분석 요청" }));
    const message = await screen.findByText(new RegExp(code === "ANALYSIS_ACTIVATION_UNAVAILABLE" ? "이 환경에서는 분석 실행이 활성화되어 있지 않아" : "분석 실행 활성화가 만료되어"));
    expect(message.textContent).toContain("관리자");
    expect(screen.getByText("보류된 요청은 분석 실행 활성화가 복구되기 전에는 처리되지 않습니다. 활성화 상태가 확인된 뒤 다시 시도하거나 보류 요청을 취소하세요.")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1]?.[1]?.headers["Idempotency-Key"]).toBe(fetchMock.mock.calls[0]?.[1]?.headers["Idempotency-Key"]);
    await waitFor(() => expect((screen.getByRole("button", { name: "보류 요청 취소" }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: "보류 요청 취소" }));
    expect(screen.queryByRole("button", { name: "다시 시도" })).toBeNull();
    expect(sessionStorage.length).toBe(0);
  });

  it("restores the activation gate message and error after a refresh", async () => {
    const code = "ANALYSIS_ACTIVATION_UNAVAILABLE";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(json({ code }, 503)));
    const props = { initialPage: listPage([]), initialSelectedDetail: null, initialAnalysisId: null, canCreate: true };
    const firstRender = renderPanel(props);

    fireEvent.change(screen.getByLabelText("작업구역"), { target: { value: "area-1" } });
    fireEvent.change(screen.getByLabelText("기준 관측"), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText("현재 관측"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "분석 요청" }));
    await screen.findByText(/이 환경에서는 분석 실행이 활성화되어 있지 않아/);

    const stored = JSON.parse(sessionStorage.getItem("ksi.analysis.pending.v2:org-1:operator-1:site-1") ?? "null");
    expect(stored.version).toBe(2);
    expect(stored.attempt.activationBlockCode).toBe(code);
    firstRender.unmount();

    renderPanel(props);
    await screen.findByText(/이 환경에서는 분석 실행이 활성화되어 있지 않아/);
    expect(screen.getByText("보류된 요청은 분석 실행 활성화가 복구되기 전에는 처리되지 않습니다. 활성화 상태가 확인된 뒤 다시 시도하거나 보류 요청을 취소하세요.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "다시 시도" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "보류 요청 취소" })).toBeTruthy();
  });

  it("keeps the generic pending notice after refresh when the failure was not an activation gate", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(json({ error: "temporary" }, 503)));
    const props = { initialPage: listPage([]), initialSelectedDetail: null, initialAnalysisId: null, canCreate: true };
    const firstRender = renderPanel(props);

    fireEvent.change(screen.getByLabelText("작업구역"), { target: { value: "area-1" } });
    fireEvent.change(screen.getByLabelText("기준 관측"), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText("현재 관측"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "분석 요청" }));
    await screen.findByText("요청을 다시 시도하세요.");

    const stored = JSON.parse(sessionStorage.getItem("ksi.analysis.pending.v2:org-1:operator-1:site-1") ?? "null");
    expect(stored.version).toBe(2);
    expect(stored.attempt.activationBlockCode).toBeNull();
    firstRender.unmount();

    renderPanel(props);
    expect(await screen.findByText("중단된 요청이 있습니다. 다시 시도하면 같은 요청 식별자로 Core에 확인합니다.")).toBeTruthy();
    expect(screen.queryByText(/보류된 요청은 분석 실행 활성화가 복구되기 전에는 처리되지 않습니다/)).toBeNull();
  });

  it("continues to restore strictly shaped version 1 pending attempts as generic", async () => {
    sessionStorage.setItem("ksi.analysis.pending.v1:org-1:operator-1:site-1", JSON.stringify({
      version: 1,
      organizationId: "org-1",
      principalId: "operator-1",
      siteId: "site-1",
      attempt: {
        key: "analysis-existing-attempt",
        workAreaId: "area-1",
        body: { baseline: observations[0]!.selector, current: observations[1]!.selector },
      },
    }));
    renderPanel({ initialPage: listPage([]), initialSelectedDetail: null, initialAnalysisId: null, canCreate: true });

    expect(await screen.findByText("중단된 요청이 있습니다. 다시 시도하면 같은 요청 식별자로 Core에 확인합니다.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "다시 시도" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "보류 요청 취소" })).toBeTruthy();
    const stored = JSON.parse(sessionStorage.getItem("ksi.analysis.pending.v2:org-1:operator-1:site-1") ?? "null");
    expect(stored.version).toBe(2);
    expect(stored.attempt.activationBlockCode).toBeNull();
    expect(sessionStorage.getItem("ksi.analysis.pending.v1:org-1:operator-1:site-1")).toBeNull();
  });

  it("discards version 2 pending attempts that contain unexpected keys", async () => {
    sessionStorage.setItem("ksi.analysis.pending.v2:org-1:operator-1:site-1", JSON.stringify({
      version: 2,
      organizationId: "org-1",
      principalId: "operator-1",
      siteId: "site-1",
      attempt: {
        key: "analysis-malformed-attempt",
        workAreaId: "area-1",
        body: { baseline: observations[0]!.selector, current: observations[1]!.selector },
        activationBlockCode: null,
        unexpected: true,
      },
    }));
    renderPanel({ initialPage: listPage([]), initialSelectedDetail: null, initialAnalysisId: null, canCreate: true });

    await waitFor(() => expect(sessionStorage.getItem("ksi.analysis.pending.v2:org-1:operator-1:site-1")).toBeNull());
    expect(screen.queryByRole("button", { name: "다시 시도" })).toBeNull();
    expect(screen.queryByText("중단된 요청이 있습니다. 다시 시도하면 같은 요청 식별자로 Core에 확인합니다.")).toBeNull();
  });

  it("loads the next bounded list page and selects its Core summary", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(detail()))
      .mockResolvedValueOnce(json(listPage(["analysis-next"], null)))
      .mockResolvedValueOnce(json(detail("analysis-next")));
    vi.stubGlobal("fetch", fetchMock);
    renderPanel({ initialPage: listPage(["analysis-1"], "list-cursor"), initialSelectedDetail: detail() });
    fireEvent.click(screen.getByRole("button", { name: "다음 분석 보기" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/sites/site-1/analyses/analysis-1",
      "/api/sites/site-1/analyses?limit=50&cursor=list-cursor",
    ]);
    await waitFor(() => expect(document.body.textContent).toContain("analysis-next"));
    expect(fetchMock).toHaveBeenCalledWith("/api/sites/site-1/analyses/analysis-1", expect.objectContaining({ cache: "no-store" }));
    expect(fetchMock).toHaveBeenCalledWith("/api/sites/site-1/analyses?limit=50&cursor=list-cursor", expect.objectContaining({ cache: "no-store" }));
    fireEvent.click(screen.getAllByRole("button", { name: "이 분석 보기" })[1]!);
    expect(router.replace).toHaveBeenCalledWith("/sites/site-1/analysis?analysisId=analysis-next");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/sites/site-1/analyses/analysis-next", expect.any(Object)));
    expect(fetchMock.mock.calls[2]![0]).toBe("/api/sites/site-1/analyses/analysis-next");
  });

  it("restarts later list pages from the refreshed first-page cursor", async () => {
    const oldFirstPage = Array.from({ length: 50 }, (_, index) => `analysis-${100 - index}`);
    const refreshedFirstPage = Array.from({ length: 50 }, (_, index) => `analysis-${101 - index}`);
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(detail()))
      .mockResolvedValueOnce(json(listPage(Array.from({ length: 50 }, (_, index) => `analysis-${50 - index}`), null)))
      .mockResolvedValueOnce(json(listPage(refreshedFirstPage, "fresh-cursor")))
      .mockResolvedValueOnce(json(detail()))
      .mockResolvedValueOnce(json(listPage(Array.from({ length: 50 }, (_, index) => `analysis-${51 - index}`), null)));
    vi.stubGlobal("fetch", fetchMock);
    renderPanel({ initialPage: listPage(oldFirstPage, "old-cursor"), initialSelectedDetail: detail() });

    fireEvent.click(screen.getByRole("button", { name: "다음 분석 보기" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(screen.getByText("분석 analysis-1")).toBeTruthy();

    fireEvent.focus(window);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
    await waitFor(() => expect(screen.queryByText("분석 analysis-50")).toBeNull());
    expect(screen.getByText("분석 analysis-101")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "다음 분석 보기" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(5));
    expect(fetchMock.mock.calls[4]![0]).toBe("/api/sites/site-1/analyses?limit=50&cursor=fresh-cursor");
    await waitFor(() => expect(screen.getByText("분석 analysis-51")).toBeTruthy());
  });

  it("pages typed evidence and restarts when Core marks a cursor stale", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(detail()))
      .mockResolvedValueOnce(json(evidencePage("LIMIT-A", "evidence-cursor")))
      .mockResolvedValueOnce(json(evidencePage("LIMIT-B", "second-cursor")))
      .mockResolvedValueOnce(json({ code: "ANALYSIS_EVIDENCE_CURSOR_STALE" }, 409))
      .mockResolvedValueOnce(json(evidencePage("LIMIT-C", null)));
    vi.stubGlobal("fetch", fetchMock);
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: "근거 확인" }));
    await waitFor(() => expect(screen.getByLabelText("근거").textContent).toContain("LIMIT-A"));
    fireEvent.click(screen.getByRole("button", { name: "다음 근거 보기" }));
    await waitFor(() => expect(screen.getByLabelText("근거").textContent).toContain("LIMIT-B"));
    expect(fetchMock.mock.calls[2]![0]).toBe("/api/sites/site-1/analyses/analysis-1/evidence?limit=32&cursor=evidence-cursor");
    expect(screen.getByLabelText("근거").textContent).toContain("현재 불러온 2개 항목");

    fireEvent.click(screen.getByRole("button", { name: "다음 근거 보기" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "근거 처음부터 다시 불러오기" }));
    await waitFor(() => expect(screen.getByLabelText("근거").textContent).toContain("LIMIT-C"));
    expect(fetchMock.mock.calls[4]![0]).toBe("/api/sites/site-1/analyses/analysis-1/evidence?limit=32");
  });

  it("loads a selected detail by ID even when it is not in the first list page", async () => {
    const old = detail("analysis-old");
    const fetchMock = vi.fn().mockResolvedValueOnce(json(old));
    vi.stubGlobal("fetch", fetchMock);
    renderPanel({ initialPage: listPage(["analysis-recent"]), initialSelectedDetail: null, initialAnalysisId: "analysis-old" });
    await screen.findByText("분석 analysis-old");
    expect(fetchMock).toHaveBeenCalledWith("/api/sites/site-1/analyses/analysis-old", expect.objectContaining({ cache: "no-store" }));
  });

  it("guides viewers in task language without exposing the permission token", () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(detail())));
    const first = renderPanel({ canCreate: false });
    expect(screen.getByText("분석 기록을 조회할 수 있습니다. 새 분석 요청은 권한 있는 현장 담당자에게 맡겨 주세요.")).toBeTruthy();
    expect(document.body.textContent).not.toContain("SITES_WRITE");
    first.unmount();

    const failed = { ...detail(), executionState: "FAILED" as const, suitabilityState: "REASSESSMENT_REQUIRED" as const, result: null };
    const page = listPage(["analysis-1"]);
    page.items[0] = { ...page.items[0]!, executionState: "FAILED", suitabilityState: "REASSESSMENT_REQUIRED", resultId: null, metrics: null };
    renderPanel({ initialPage: page, initialSelectedDetail: failed, canCreate: false });
    expect(screen.getByText("Core가 분석을 완료하지 못했습니다. 현장 분석 담당자에게 실패 사유와 근거 검토를 요청하세요.")).toBeTruthy();
    expect(document.body.textContent).not.toContain("SITES_WRITE");
  });

  it("collapses loaded evidence back to the initial confirm action", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(json(detail()))
      .mockResolvedValueOnce(json(evidencePage("LIMIT-A", null))));
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: "근거 확인" }));
    const collapse = await screen.findByRole("button", { name: "근거 닫기 · 1개 항목" });
    expect(collapse.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(collapse);
    expect(await screen.findByRole("button", { name: "근거 확인" })).toBeTruthy();
    expect(screen.queryByLabelText("근거")).toBeNull();
  });

  it("keeps evidence-specific restrictions visible while technical details are collapsed", async () => {
    const page = evidencePage("LIMIT-A", null);
    page.items[0]!.limitationCodes = ["CHECKPOINT_NOT_INDEPENDENT"];
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(json(detail()))
      .mockResolvedValueOnce(json(page)));
    renderPanel();

    fireEvent.click(screen.getByRole("button", { name: "근거 확인" }));
    const notice = await screen.findByText("이 근거의 제한 · 독립성이 확인되지 않은 검사점 근거");
    const summary = notice.closest("summary");
    expect(summary).not.toBeNull();
    expect(summary!.closest("details")?.hasAttribute("open")).toBe(false);
  });
});
