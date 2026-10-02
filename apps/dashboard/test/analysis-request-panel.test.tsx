/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const router = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

import { AnalysisRequestPanel } from "@/app/sites/[siteId]/analysis/AnalysisRequestPanel";
import type { AnalysisEvidencePage, AnalysisListPage, AnalysisObservationOption, AnalysisView } from "@/lib/core-api/analysis";

const selector = (workOrderId: string, digit: string) => ({ workOrderId, submissionRef: `ers-v1-${digit.repeat(64)}`, revision: 1 });
const observations: AnalysisObservationOption[] = [
  { selector: selector("work-baseline", "a"), observationEpochId: "epoch-baseline", captureStartedAt: "2026-09-01T00:00:00Z", captureEndedAt: "2026-09-01T00:30:00Z" },
  { selector: selector("work-current", "b"), observationEpochId: "epoch-current", captureStartedAt: "2026-09-08T00:00:00Z", captureEndedAt: "2026-09-08T00:30:00Z" },
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
    expect(screen.getByText("result-core-1")).toBeTruthy();
    expect(screen.getByText((_text, element) => element?.textContent === "제한: PROVISIONAL_ACCURACY_UNVERIFIED, INSPECTION_LIMITED")).toBeTruthy();
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
    expect(screen.getByText("근거 · 2개 항목")).toBeTruthy();

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
});
