/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const router = vi.hoisted(() => ({ replace: vi.fn(), refresh: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

import { AnalysisRequestPanel } from "@/app/sites/[siteId]/analysis/AnalysisRequestPanel";
import type { AnalysisEvidencePage, AnalysisListPage, AnalysisObservationOption, AnalysisReviewReceipt, AnalysisReviewTarget, AnalysisView } from "@/lib/core-api/analysis";

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
const reviewTarget: AnalysisReviewTarget = {
  resultId: result.resultId,
  resultRevision: 1,
  reportDigest: result.reportDigest,
  numericResultIdentityDigest: result.numericResultIdentityDigest,
  calculationIdentityDigest: `sha256:${"6".repeat(64)}`,
  admissionDigest: `sha256:${"7".repeat(64)}`,
  evaluations: [
    { epoch: "BASELINE", evaluationId: "evaluation-baseline", revision: 1, evaluationDigest: `sha256:${"8".repeat(64)}` },
    { epoch: "CURRENT", evaluationId: "evaluation-current", revision: 2, evaluationDigest: `sha256:${"9".repeat(64)}` },
  ],
};

function reviewReceipt(decision: AnalysisReviewReceipt["decision"] = "ACKNOWLEDGED"): AnalysisReviewReceipt {
  return {
    reviewRef: `arv2-${"c".repeat(64)}`,
    reviewerId: "operator-reviewer-1",
    decision,
    comment: "현재 결과와 근거를 확인했습니다.",
    reviewedAt: "2026-10-15T05:30:00Z",
    receiptDigest: `sha256:${"d".repeat(64)}`,
    target: reviewTarget,
    factualLimitations: [
      "HUMAN_REVIEW_IS_NOT_ACCURACY_VALIDATION",
      "HUMAN_REVIEW_IS_NOT_FIELD_OR_FLIGHT_AUTHORIZATION",
      "RELATIVE_VOLUME_IS_NOT_SETTLEMENT_OR_COMPLETION_PROOF",
    ],
  };
}

function reviewPage(items: AnalysisReviewReceipt[] = []) {
  return { target: reviewTarget, items, nextCursor: null };
}

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

function listItem(analysisId: string, newerSiblingAnalysisIds: string[] = []) {
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
    newerSiblingAnalysisIds,
  };
}

function listPage(
  items: string[],
  nextCursor: string | null = null,
  siblings: Record<string, string[]> = {},
): AnalysisListPage {
  return {
    siteId: "site-1",
    items: items.map((analysisId) => listItem(analysisId, siblings[analysisId] ?? [])),
    nextCursor,
  };
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

function renderPanel(
  overrides: Partial<Parameters<typeof AnalysisRequestPanel>[0]> = {},
  reviewFetch?: (url: string, init?: RequestInit) => Promise<Response>,
) {
  const initial = detail();
  const delegateFetch = globalThis.fetch;
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    if (/\/reviews(?:\?|$)/.test(url)) {
      if (reviewFetch) return reviewFetch(url, init);
      if (init?.method !== "POST") return Promise.resolve(json(reviewPage()));
    }
    return delegateFetch(input, init);
  }));
  return render(<AnalysisRequestPanel
    siteId="site-1"
    {...scope}
    workAreas={[{ workAreaId: "area-1", name: "1구역" }]}
    observations={overrides.observations ?? observations}
    siteObservations={overrides.siteObservations ?? overrides.observations ?? observations}
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
  it.each([null, "analysis-1"])("surfaces a restored pending request before a long history (deep link: %s) and retries the frozen input", async (initialAnalysisId) => {
    const body = { baseline: observations[0]!.selector, current: observations[1]!.selector };
    sessionStorage.setItem("ksi.analysis.pending.v2:org-1:operator-1:site-1", JSON.stringify({
      version: 2, ...scope, siteId: "site-1",
      attempt: { key: "analysis-existing-attempt", workAreaId: "area-1", body, activationBlockCode: null },
    }));
    const fetchMock = vi.fn().mockResolvedValue(json({ error: "temporary" }, 503));
    vi.stubGlobal("fetch", fetchMock);
    renderPanel({ initialPage: listPage(Array.from({ length: 20 }, (_, i) => `analysis-${i + 1}`)), initialAnalysisId, canCreate: true });
    const notice = await screen.findByRole("region", { name: "보류 요청 안내" });
    const history = screen.getByRole("region", { name: "변화 분석 이력" });
    const request = screen.getByRole("region", { name: "새 변화 분석 요청" });
    expect(notice.compareDocumentPosition(history) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(history.compareDocumentPosition(request) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(notice).getByRole("link", { name: "보류 요청 이어가기" }).getAttribute("href")).toBe("#new-analysis-request");
    expect((screen.getByLabelText("기준 관측") as HTMLSelectElement).value).toBe("0");
    expect((screen.getByLabelText("현재 관측") as HTMLSelectElement).value).toBe("1");
    fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(true));
    const init = fetchMock.mock.calls.find(([, options]) => options?.method === "POST")![1]!;
    expect(init.headers["Idempotency-Key"]).toBe("analysis-existing-attempt");
    expect(JSON.parse(init.body)).toEqual(body);
  });

  it.each([0, 20])("keeps form, focus and order while submitting with %i prior records", async (count) => {
    let resolvePost!: (response: Response) => void;
    const post = new Promise<Response>((resolve) => { resolvePost = resolve; });
    vi.stubGlobal("fetch", vi.fn((_input, init) => init?.method === "POST" ? post : Promise.resolve(json(detail()))));
    renderPanel({ initialPage: listPage(Array.from({ length: count }, (_, i) => `analysis-${i + 1}`)), initialSelectedDetail: count ? detail() : null, initialAnalysisId: null, canCreate: true });
    fireEvent.change(screen.getByLabelText("작업구역"), { target: { value: "area-1" } });
    fireEvent.change(screen.getByLabelText("기준 관측"), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText("현재 관측"), { target: { value: "1" } });
    const request = screen.getByRole("region", { name: "새 변화 분석 요청" });
    const summary = within(request).getByText("선택지 표시 방법");
    if (count) expect(screen.getByRole("region", { name: "변화 분석 이력" }).compareDocumentPosition(request) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "변화 분석 요청" }));
    summary.focus();
    expect(document.activeElement).toBe(summary);
    const created = detail("analysis-created", "QUEUED");
    resolvePost(json(created, 202));
    await screen.findByText(/요청이 접수됐습니다/);
    expect(screen.getByRole("region", { name: "새 변화 분석 요청" })).toBe(request);
    expect(document.activeElement).toBe(summary);
    expect(screen.getByRole("region", { name: "변화 분석 이력" }).compareDocumentPosition(request) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect((screen.getByLabelText("기준 관측") as HTMLSelectElement).value).toBe("0");
    expect((screen.getByLabelText("현재 관측") as HTMLSelectElement).value).toBe("1");
  });

  it("names a confirmed blocked suitability separately from an unknown state", () => {
    const blocked = { ...detail(), suitabilityState: "BLOCKED" as const };
    vi.stubGlobal("fetch", vi.fn());
    renderPanel({ initialSelectedDetail: blocked });
    const resultRegion = screen.getByRole("region", { name: /계산 결과/ });
    expect(within(resultRegion).getByText(/현재 적합성은 차단되었습니다/)).toBeTruthy();
    expect(within(resultRegion).queryByText(/적합성 상태를 확인하지 못했습니다/)).toBeNull();
  });

  it("keeps an unrecognized suitability distinct from a confirmed block", () => {
    const unknown = { ...detail(), suitabilityState: "FUTURE_STATE" as AnalysisView["suitabilityState"] };
    vi.stubGlobal("fetch", vi.fn());
    renderPanel({ initialSelectedDetail: unknown });
    const resultRegion = screen.getByRole("region", { name: /계산 결과/ });
    expect(within(resultRegion).getByText(/적합성 상태를 확인하지 못했습니다/)).toBeTruthy();
    expect(within(resultRegion).queryByText(/현재 적합성은 차단되었습니다/)).toBeNull();
  });
  it("prioritizes the recorded result before the separate request and keeps the accuracy limit beside its numbers", () => {
    vi.stubGlobal("fetch", vi.fn());
    renderPanel({ canCreate: true });
    const history = screen.getByRole("region", { name: "변화 분석 이력" });
    const request = screen.getByRole("region", { name: "새 변화 분석 요청" });
    expect(history.compareDocumentPosition(request) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("link", { name: "새 변화 분석 요청으로 이동" }).getAttribute("href")).toBe("#new-analysis-request");
    const resultRegion = within(history).getByRole("region", { name: /계산 결과/ });
    expect(within(resultRegion).getByText(/독립 정확도 평가는 아직 확인되지 않았습니다/)).toBeTruthy();
    expect(within(resultRegion).getByText("절토")).toBeTruthy();
    expect(within(history).getByText("실행 상태")).toBeTruthy();
    expect(within(history).getByText("적합성 상태")).toBeTruthy();
  });
  it("bridges the exact selected record into the shared workspace result mode", () => {
    vi.stubGlobal("fetch", vi.fn());
    const context = { workAreaId: "area-1", visualAAssetRef: `ksa-v1-${"a".repeat(64)}`, visualBAssetRef: `ksa-v1-${"b".repeat(64)}` };
    renderPanel({ visualContext: context });
    const bridge = screen.getByRole("link", { name: "작업공간에서 결과 보기" });
    const href = bridge.getAttribute("href")!;
    // frozen 기록 신원 그대로 — 최신 추론·다른 기록 대체 없음.
    expect(href).toContain("/sites/site-1?mode=results");
    expect(href).toContain("workAreaId=area-1");
    expect(href).toContain("analysisId=analysis-1");
    // 같은 구역 검증 쌍만 덧붙인다.
    expect(href).toContain(`visualAAssetRef=${context.visualAAssetRef}`);
    expect(href).toContain(`visualBAssetRef=${context.visualBAssetRef}`);
    expect(href).not.toContain("mode=compare");
  });

  it("drops a foreign-area visual context from the workspace bridge", () => {
    vi.stubGlobal("fetch", vi.fn());
    renderPanel({ visualContext: { workAreaId: "other-area", visualAAssetRef: `ksa-v1-${"a".repeat(64)}`, visualBAssetRef: `ksa-v1-${"b".repeat(64)}` } });
    const href = screen.getByRole("link", { name: "작업공간에서 결과 보기" }).getAttribute("href")!;
    expect(href).not.toContain("visualAAssetRef");
    expect(href).not.toContain("visualBAssetRef");
    expect(href).toContain("analysisId=analysis-1");
  });
  it.each([null, "analysis-1"])("orders the exact draft before history, but keeps a fixed result first (%s)", (initialAnalysisId) => {
    renderPanel({canCreate:true,initialAnalysisId,initialWorkAreaId:"area-1",initialBaselineSelector:observations[0]!.selector,initialCurrentSelector:observations[1]!.selector});
    const request = document.getElementById("new-analysis-request")!;
    const history = document.getElementById("analysis-history")!;
    expect(Boolean(request.compareDocumentPosition(history) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(initialAnalysisId === null);
    expect(document.querySelectorAll('#new-analysis-request')).toHaveLength(1);
  });

  it("makes only the latest record's view button primary and keeps one browse return", () => {
    vi.stubGlobal("fetch", vi.fn());
    renderPanel({
      canCreate: true,
      initialPage: listPage(["analysis-2", "analysis-1"]),
      initialAnalysisId: "analysis-1",
      initialSelectedDetail: detail("analysis-1"),
      visualContext: { workAreaId: "area-1", visualAAssetRef: `ksa-v1-${"a".repeat(64)}`, visualBAssetRef: `ksa-v1-${"b".repeat(64)}` },
      visualReturnHref: "/sites/site-1?mode=compare&workAreaId=area-1",
    });
    // 최신 기록 카드의 보기 단추만 1차 동작이다.
    const viewButtons = screen.getAllByRole("button", { name: "이 변화 분석 보기" });
    expect(viewButtons).toHaveLength(2);
    expect(viewButtons[0]!.className).toContain("btn-primary");
    expect(viewButtons[1]!.className).not.toContain("btn-primary");
    // 탐색 복귀는 맨 위 맥락 띠 하나뿐이다.
    expect(screen.getAllByRole("link", { name: "독립 보기로 돌아가기" })).toHaveLength(1);
    // 나머지는 조용한 링크 행에 있다.
    expect(screen.getByRole("link", { name: "작업공간에서 결과 보기" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /근거 확인/ })).toBeTruthy();
  });

  it("shows the selected record's calculation inputs near the summary from validated candidates", () => {
    vi.stubGlobal("fetch", vi.fn());
    renderPanel({ canCreate: true });
    // 기록의 frozen 선택자를 현재 후보에서 검증해 라벨로 둔다 — 탐색 쌍을 쓰지 않는다.
    const pairLine = screen.getByText(/계산 입력 · 기준/);
    expect(pairLine.textContent).toContain("현재");
    expect(pairLine.textContent).toMatch(/2026/);
    expect(screen.queryByText(/원래 입력을 현재 목록에서 확인할 수 없습니다/)).toBeNull();
  });

  it("says unknown instead of inferring inputs the current list cannot validate", () => {
    vi.stubGlobal("fetch", vi.fn());
    const unknown = (workOrderId: string, digit: string) => ({ workOrderId, submissionRef: `ers-v1-${digit.repeat(64)}`, revision: 9 });
    const stale = { ...detail("analysis-9"), baseline: unknown("work-old", "c"), current: unknown("work-older", "d") };
    renderPanel({ canCreate: true, initialAnalysisId: "analysis-9", initialSelectedDetail: stale });
    expect(screen.getByText(/원래 입력을 현재 목록에서 확인할 수 없습니다/)).toBeTruthy();
    expect(screen.queryByText(/계산 입력 · 기준/)).toBeNull();
  });

  it("keeps existing records before the request form for a bare browse context", () => {
    vi.stubGlobal("fetch", vi.fn());
    const context = { workAreaId: "area-1", visualAAssetRef: `ksa-v1-${"a".repeat(64)}`, visualBAssetRef: `ksa-v1-${"b".repeat(64)}` };
    const recorded = detail();
    renderPanel({ canCreate: true, initialAnalysisId: null,
      initialPage: listPage([recorded.analysisId]), initialSelectedDetail: recorded,
      visualContext: context, visualReturnHref: "/sites/site-1?mode=compare&workAreaId=area-1" });
    // 기록이 있으면 이력이 요청보다 먼저 보인다.
    const request = document.getElementById("new-analysis-request")!;
    const history = document.getElementById("analysis-history")!;
    expect(Boolean(history.compareDocumentPosition(request) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true);
    // 복귀 다리는 기록보다 먼저 둔다.
    expect(screen.getAllByRole("link", { name: "독립 보기로 돌아가기" }).length).toBeGreaterThan(0);
    expect(screen.queryByText("요청한 관측이 분석 후보와 정확히 맞지 않아")).toBeNull();
  });

  it("retains a read-only return path even without a result or request permission", () => {
    vi.stubGlobal("fetch", vi.fn());
    const context = {workAreaId:"area-1",visualAAssetRef:`ksa-v1-${"a".repeat(64)}`,visualBAssetRef:`ksa-v1-${"b".repeat(64)}`};
    const href = `/sites/site-1?mode=compare&workAreaId=area-1&visualAAssetRef=${context.visualAAssetRef}&visualBAssetRef=${context.visualBAssetRef}`;
    renderPanel({ initialPage: {siteId:"site-1",items:[],nextCursor:null}, initialAnalysisId:null, initialSelectedDetail:null,
      canCreate:false, visualContext:context, visualReturnHref:href });
    const nav = screen.getByRole("navigation", {name:"독립 보기 복귀"});
    expect(within(nav).getByRole("link", {name:"독립 보기로 돌아가기"}).getAttribute("href")).toBe(href);
    expect(screen.queryByRole("button", {name:"변화 분석 요청"})).toBeNull();
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it("keeps the handoff explanation outside compact-screen mutation gating", () => {
    vi.stubGlobal("fetch", vi.fn());
    renderPanel({ canCreate:true, initialPage:{siteId:"site-1",items:[],nextCursor:null},initialAnalysisId:null,initialSelectedDetail:null,
      exactHintNotice:"정확한 분석 후보를 확인하지 못했습니다.", visualContext:{workAreaId:"area-1",visualAAssetRef:`ksa-v1-${"a".repeat(64)}`,visualBAssetRef:`ksa-v1-${"b".repeat(64)}`},
      visualReturnHref:"/sites/site-1?mode=compare" });
    const message = screen.getByText("정확한 분석 후보를 확인하지 못했습니다.");
    expect(message.closest(".hidden")).toBeNull();
    expect(screen.getByRole("button", {name:"변화 분석 요청",hidden:true}).closest(".hidden")).not.toBeNull();
    expect(document.getElementById("new-analysis-request")?.className).toContain("scroll-mt-20");
    // 기록이 없으면 단일 열로 요청만 둔다 — 이력 섹션은 만들지 않는다.
    expect(document.getElementById("new-analysis-request")).toBeTruthy();
    expect(document.getElementById("analysis-history")).toBeNull();
  });

  it("renders compact metric definitions without a forced-width horizontal table", () => {
    renderPanel();

    const metricsRegion = screen.getByRole("region", { name: /^계산 결과/ });
    expect(metricsRegion.querySelector("table")).toBeNull();
    expect(metricsRegion.querySelector("dl")?.className).toContain("sm:grid-cols-3");
    expect([...metricsRegion.querySelectorAll("[class]")].some((element) => element.getAttribute("class")?.includes("min-w-[24rem]") ?? false)).toBe(false);
    expect(within(metricsRegion).getByText("절토")).toBeTruthy();
    expect(within(metricsRegion).getByText("12 m³")).toBeTruthy();
    expect(within(metricsRegion).getByText("성토")).toBeTruthy();
    expect(within(metricsRegion).getByText("20 m³")).toBeTruthy();
    expect(within(metricsRegion).getByText("순변화")).toBeTruthy();
    expect(within(metricsRegion).getByText("8 m³")).toBeTruthy();
  });

  it("distinguishes result landmarks for analyses created in the same minute", () => {
    vi.stubGlobal("fetch", vi.fn());
    const first = "analysis-v1-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa1";
    const second = "analysis-v1-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa2";
    renderPanel({
      initialPage: listPage([first, second]),
      initialAnalysisId: first,
      initialSelectedDetail: detail(first),
    });

    const regions = screen.getAllByRole("region", { name: /^계산 결과/ });
    expect(regions).toHaveLength(2);
    const names = regions.map((region) => region.getAttribute("aria-label"));
    expect(new Set(names).size).toBe(2);
    expect(names.some((name) => name?.includes(first))).toBe(true);
    expect(names.some((name) => name?.includes(second))).toBe(true);
  });

  it("shows one neutral notice for a shared-epoch continuation when capture time is unavailable", () => {
    // Core 목록의 공유 epoch 연결만 있고 관측 시각은 없는 경우다.
    // 시간 파생 알림이 불가능해도 같은 자리에서 중립 한 줄로 알린다.
    renderPanel({
      observations: [],
      siteObservations: [],
      initialPage: listPage(["analysis-1"], null, { "analysis-1": ["analysis-2"] }),
      initialSelectedDetail: detail("analysis-1"),
      initialAnalysisId: "analysis-1",
    });

    const notice = screen.getByText(/이 작업구역에 이 기록의 현재 관측을 기준으로 삼은 새 분석이 있습니다/);
    expect(notice).toBeTruthy();
    expect(notice.textContent).toContain("이 기록의 수치·상태는 그대로 둡니다.");
    expect(notice.textContent).not.toMatch(/대체됨|구버전|최신|신뢰할 수 없/);
    const link = within(notice).getByRole("link", { name: "새 분석 결과 보기" });
    expect(link.getAttribute("href")).toBe("/sites/site-1/analysis?analysisId=analysis-2");
    // 두 번째 알림을 만들지 않는다.
    expect(screen.queryByText(/더 새 관측이 있습니다/)).toBeNull();
  });

  it("shows no continuation notice when the Core list carries no shared-epoch link", () => {
    renderPanel({
      observations: [],
      siteObservations: [],
      initialPage: listPage(["analysis-1"]),
      initialSelectedDetail: detail("analysis-1"),
      initialAnalysisId: "analysis-1",
    });

    expect(screen.queryByText(/새 분석이 있습니다/)).toBeNull();
    expect(screen.queryByText(/더 새 관측이 있습니다/)).toBeNull();
  });

  it("uses a true-empty message only after a successful list read", async () => {
    renderPanel({ initialPage: listPage([]), initialSelectedDetail: null, initialAnalysisId: null, canCreate: true,
      observations: [], siteObservations: [] });
    expect(screen.getByText(/이 현장에는 아직 변화 분석 요청이 없습니다/)).toBeTruthy();
    expect(screen.getByText(/실제 작업구역과 관측 후보를 확인/)).toBeTruthy();

    cleanup();
    let finishRequest: ((value: Response) => void) | undefined;
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((resolve) => { finishRequest = resolve; })));
    renderPanel({ initialPage: listPage([], "older-cursor"), initialSelectedDetail: null, initialAnalysisId: null, canCreate: false,
      observations: [], siteObservations: [] });
    expect(screen.getByText(/현재 페이지에 변화 분석 요청이 없습니다/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "다음 변화 분석 보기" }));
    expect(screen.getByRole("status").textContent).toContain("변화 분석 목록을 불러오는 중입니다.");
    expect(screen.queryByText(/현재 페이지에 변화 분석 요청이 없습니다/)).toBeNull();
    finishRequest?.({ ok: false, status: 503, json: async () => ({}) } as Response);
    expect((await screen.findByRole("alert")).textContent).toContain("변화 분석 목록");
    expect(screen.queryByText(/현재 페이지에 변화 분석 요청이 없습니다|이 현장에는 아직 변화 분석 요청이 없습니다/)).toBeNull();
  });

  it("names the real work with capture interval and submission version, keeping exact selectors inspectable", () => {
    renderPanel({ initialPage: listPage([]), initialSelectedDetail: null, initialAnalysisId: null, canCreate: true, workOrderNames: { "work-baseline": "기준 작업", "work-current": "현재 작업" } });

    const baseline = screen.getByLabelText("기준 관측") as HTMLSelectElement;
    const current = screen.getByLabelText("현재 관측") as HTMLSelectElement;
    expect(baseline.value).toBe("");
    expect(current.value).toBe("");
    expect(baseline.disabled).toBe(true);
    expect(screen.getByText("기준·현재 관측을 고르면 Core가 권한·자료 적합성·계산 실행을 확인합니다. 판단은 요청 시 Core가 하며, 기준이 비어 있을 때만 가장 최근 선행 관측을 제안합니다.")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("작업구역"), { target: { value: "area-1" } });
    expect(baseline.options[1]?.textContent).toContain("기준 작업");
    expect(baseline.options[1]?.textContent).toContain("2026. 9. 1.");
    expect(baseline.options[1]?.textContent).toContain("09:00–09:30");
    expect(baseline.options[1]?.textContent).not.toContain("등록 버전");
    expect(baseline.options[1]?.textContent).not.toContain("epoch-baseline");

    fireEvent.change(baseline, { target: { value: "0" } });
    fireEvent.change(current, { target: { value: "1" } });
    const confirmation = screen.getByText("선택 확인").closest("div")!;
    expect(confirmation.textContent).toContain("기준");
    expect(confirmation.textContent).toContain("기준 작업");
    expect(confirmation.textContent).toContain("현재");
    expect(confirmation.textContent).toContain("현재 작업");

    const selectorDetails = screen.getByText("요청 선택 정보 전체 확인").closest("details");
    expect(selectorDetails?.hasAttribute("open")).toBe(false);
    fireEvent.click(screen.getByText("요청 선택 정보 전체 확인"));
    expect(selectorDetails?.textContent).toContain(observations[0]!.selector.submissionRef);
    expect(selectorDetails?.textContent).toContain("work-baseline");
    expect(selectorDetails?.textContent).toContain("관측 기록 ID · epoch-baseline");
    expect(selectorDetails?.textContent).toContain("등록 버전 1");
  });

  it("stays honest about missing work names and only falls back to epoch IDs on collision", () => {
    renderPanel({ initialPage: listPage([]), initialSelectedDetail: null, initialAnalysisId: null, canCreate: true });

    fireEvent.change(screen.getByLabelText("작업구역"), { target: { value: "area-1" } });
    const baseline = screen.getByLabelText("기준 관측") as HTMLSelectElement;
    expect(baseline.options[1]?.textContent).toContain("작업명 확인 불가");
    expect(baseline.options[1]?.textContent).toContain("2026. 9. 1.");
    expect(baseline.options[1]?.textContent).not.toContain("등록 버전");
    expect(baseline.options[1]?.textContent).not.toContain("epoch-baseline");

    cleanup();
    const colliding: (AnalysisObservationOption & { workAreaIds: string[] })[] = [
      { ...observations[0]!, observationEpochId: "epoch-collide-first" },
      { ...observations[0]!, observationEpochId: "epoch-collide-second" },
    ];
    renderPanel({ observations: colliding, initialPage: listPage([]), initialSelectedDetail: null, initialAnalysisId: null, canCreate: true });
    fireEvent.change(screen.getByLabelText("작업구역"), { target: { value: "area-1" } });
    const collided = screen.getByLabelText("기준 관측") as HTMLSelectElement;
    expect(collided.options[1]?.textContent).toContain("관측 기록 epoch-collide-first");
    expect(collided.options[2]?.textContent).toContain("관측 기록 epoch-collide-second");
    expect(collided.options[1]?.textContent).not.toBe(collided.options[2]?.textContent);
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
    const selected = within(screen.getByText("분석 ID · analysis-1").closest("article")!);

    expect(selected.getByText("높이 기준이 서로 다름 · 현재 관측")).toBeTruthy();
    expect(selected.getByText(/수직 기준과 단위를 담당자가 확인해야 합니다/)).toBeTruthy();
    expect(selected.getByRole("link", { name: "공간 자산 기록 확인" }).getAttribute("href")).toBe("/sites/site-1/spatial-assets?workAreaId=area-1");
    const technical = selected.getByText("원문 코드·설명 보기").closest("details");
    expect(technical?.hasAttribute("open")).toBe(false);
    fireEvent.click(selected.getByText("원문 코드·설명 보기"));
    expect(technical?.textContent).toContain("VERTICAL_REFERENCE_MISMATCH");
    expect(technical?.textContent).toContain("height datum differs");
    expect(technical?.textContent).toContain("checkpoint-ref-1");
  });

  it("tells the artifact provider what they can do themselves, and only when they can", () => {
    // 참가자는 산출물 제공자 본인이다(2026-10-20 베타). 원인이 산출물 쪽인
    // 코드에는 직접 실행할 수 있는 조치가 붙고, 운영 조회로만 풀리는 코드에는
    // 붙지 않아야 한다.
    const blocked = {
      ...detail(),
      suitabilityState: "BLOCKED" as const,
      blockers: [{ code: "VERTICAL_REFERENCE_MISMATCH", message: null, epoch: "CURRENT" as const, evidenceRef: null, detail: null }],
      result: null,
    };
    const page = listPage(["analysis-1"]);
    page.items[0] = { ...page.items[0]!, suitabilityState: "BLOCKED", resultId: null, metrics: null, limitationCount: 1 };

    renderPanel({ initialPage: page, initialSelectedDetail: blocked });
    const selected = within(screen.getByText("분석 ID · analysis-1").closest("article")!);
    expect(selected.getByText(/산출물 제공자가 직접 할 수 있는 것/)).toBeTruthy();
    expect(selected.getByText(/높이 기준이 기록된 값과 같은지 확인하세요/)).toBeTruthy();

    cleanup();
    const operatorOnly = {
      ...detail(),
      suitabilityState: "BLOCKED" as const,
      blockers: [{ code: "REASSESSMENT_REQUIRED", message: null, epoch: null, evidenceRef: null, detail: null }],
      result: null,
    };
    renderPanel({ initialPage: page, initialSelectedDetail: operatorOnly });
    const other = within(screen.getByText("분석 ID · analysis-1").closest("article")!);
    expect(other.queryByText(/산출물 제공자가 직접 할 수 있는 것/)).toBeNull();
  });

  it("gives an honest fallback for unknown blocker codes without treating them as retryable", () => {    const blocked = {
      ...detail(),
      suitabilityState: "BLOCKED" as const,
      blockers: [{ code: "FUTURE_REASON_CODE", message: null, epoch: null, evidenceRef: null, detail: null }],
      result: null,
    };
    const page = listPage(["analysis-1"]);
    page.items[0] = { ...page.items[0]!, suitabilityState: "BLOCKED", resultId: null, metrics: null, limitationCount: 1 };

    renderPanel({ initialPage: page, initialSelectedDetail: blocked });
    const selected = within(screen.getByText("분석 ID · analysis-1").closest("article")!);
    expect(selected.getByText("세부 원인 확인 필요")).toBeTruthy();
    expect(selected.getByText(/이 사유에 대한 화면 안내가 없습니다/)).toBeTruthy();
    expect(selected.getByText(/반복 요청하지 마세요/)).toBeTruthy();
    expect(selected.getByText("원문 코드·설명 보기").closest("details")?.hasAttribute("open")).toBe(false);
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

    const selected = within(screen.getByText("분석 ID · analysis-1").closest("article")!);
    expect(selected.getByText("실행 완료")).toBeTruthy();
    expect(selected.getByText("재평가 필요")).toBeTruthy();
    expect(selected.getByText("계산은 완료됐습니다. 현장 적합성은 재평가가 필요합니다.")).toBeTruthy();
    expect(selected.getByText("현장 적합성 재평가 필요")).toBeTruthy();
    expect(selected.getByText("원문 코드·설명 보기").closest("details")?.hasAttribute("open")).toBe(false);
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
    await waitFor(() => expect(within(screen.getByText("분석 ID · analysis-1").closest("article")!).getByText("result-core-1")).toBeTruthy());
    fireEvent.click(screen.getAllByRole("button", { name: "이 변화 분석 보기" })[1]!);
    await waitFor(() => expect(within(screen.getByText("분석 ID · analysis-2").closest("article")!).getByText("other-result")).toBeTruthy());
    fireEvent.click(screen.getAllByRole("button", { name: "이 변화 분석 보기" })[0]!);
    const selected = within(screen.getByText("분석 ID · analysis-1").closest("article")!);
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
    expect(screen.getByRole("button", { name: "변화 분석 상세 다시 불러오기" })).toBeTruthy();
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
    expect(screen.getByText("분석 ID · analysis-1")).toBeTruthy();
    expect(screen.getByRole("region", { name: /^계산 결과/ })).toBeTruthy();
    expect(within(screen.getByText("분석 ID · analysis-1").closest("article")!).getByText("result-core-1")).toBeTruthy();
    expect(screen.getByText("정확도 평가 미확인")).toBeTruthy();
    expect(screen.getByText("자료 검사에 제한 있음")).toBeTruthy();
    expect(screen.getByText("정확도 미확인")).toBeTruthy();
  });

  it.each([
    ["EVALUATED", /독립 평가 근거가 있습니다/],
    ["PROVISIONAL_ACCURACY_UNVERIFIED", /독립 정확도 평가는 아직 확인되지 않았습니다/],
    ["REASSESSMENT_REQUIRED", /현재 적합성은 재평가가 필요합니다/],
    ["REMEDIATION_REQUIRED", /평가 보완이 필요합니다/],
    ["BLOCKED", /현재 적합성은 차단되었습니다/],
  ] as const)("states the projected suitability truthfully beside a recorded numeric result (%s)", (suitability, pattern) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(detail())));
    const current = { ...detail(), suitabilityState: suitability };
    const page = listPage(["analysis-1"]);
    page.items[0] = { ...page.items[0]!, suitabilityState: suitability };
    renderPanel({ initialPage: page, initialSelectedDetail: current });

    // 상태별 한 줄은 다르지만 수치는 그대로 둔다 — 문구가 수치를 바꾸지 않는다.
    const card = within(screen.getByText("분석 ID · analysis-1").closest("article")!);
    expect(card.getByText(pattern)).toBeTruthy();
    expect(card.getByText("result-core-1")).toBeTruthy();
  });

  it("shows 미검토 to viewers without exposing a write action", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(detail())));
    renderPanel({ canCreate: false });

    expect(await screen.findByText("미검토")).toBeTruthy();
    expect(screen.getByText("현재 결과에 대한 검토 기록이 없습니다.")).toBeTruthy();
    expect(screen.queryByRole("radio")).toBeNull();
    const blocked = screen.getByRole("button", { name: "검토 기록 추가" });
    expect(blocked.hasAttribute("disabled")).toBe(false);
    fireEvent.click(blocked);
    expect(screen.getByText("검토 기록 추가는 현장 쓰기 권한이 있는 담당자에게 요청하세요.")).toBeTruthy();
  });

  it("shows the exact current ACKNOWLEDGED review and its expandable audit detail", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(detail())));
    const review = reviewReceipt();
    renderPanel({ canCreate: false }, async () => json(reviewPage([review])));

    expect(await screen.findByText("확인됨")).toBeTruthy();
    expect(screen.getByText(/최근 검토 · operator-reviewer-1/)).toBeTruthy();
    const summary = screen.getByText("검토 기록");
    const audit = summary.closest("details");
    expect(audit?.hasAttribute("open")).toBe(false);
    fireEvent.click(summary);
    expect(audit?.textContent).toContain(review.receiptDigest);
    expect(audit?.textContent).toContain(review.comment);
    expect(audit?.textContent).toContain(review.target.reportDigest);
    // 사람용 맥락(대상·의견·한계)이 확인값 목록보다 먼저 나온다.
    const body = audit?.textContent ?? "";
    expect(body.indexOf("검토 대상")).toBeLessThan(body.indexOf("검토 기록 확인값"));
    expect(body.indexOf("검토 의견")).toBeLessThan(body.indexOf("보고서 확인값"));
    expect(body.indexOf("검토 한계")).toBeLessThan(body.indexOf("수치 결과 확인값"));
  });

  it("treats a review with a different current-evaluation identity as 미검토", async () => {
    const staleTarget: AnalysisReviewTarget = {
      ...reviewTarget,
      evaluations: [
        reviewTarget.evaluations[0],
        { ...reviewTarget.evaluations[1], evaluationId: "previous-current-evaluation" },
      ],
    };
    const staleReview = { ...reviewReceipt(), target: staleTarget };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(detail())));
    renderPanel({ canCreate: false }, async () => json(reviewPage([staleReview])));

    expect(await screen.findByText("미검토")).toBeTruthy();
    expect(screen.getByText(/이전 결과 또는 평가/)).toBeTruthy();
    expect(screen.getByText(/최근 검토 · operator-reviewer-1/)).toBeTruthy();
  });

  it("requires a nonblank comment and enforces the 1,000-character limit by Unicode code point", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(detail())));
    renderPanel({ canCreate: true }, async () => json(reviewPage()));

    await screen.findByText("미검토");
    fireEvent.click(screen.getByLabelText("결과와 한계 확인"));
    const comment = screen.getByLabelText(/검토 의견/) as HTMLTextAreaElement;
    const submit = screen.getByRole("button", { name: "검토 기록 추가" }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);

    fireEvent.change(comment, { target: { value: "   " } });
    expect(submit.disabled).toBe(true);

    fireEvent.change(comment, { target: { value: "😀".repeat(1_000) } });
    expect(comment.getAttribute("aria-invalid")).toBe("false");
    expect(submit.disabled).toBe(false);

    fireEvent.change(comment, { target: { value: "😀".repeat(1_001) } });
    expect(comment.getAttribute("aria-invalid")).toBe("true");
    expect(submit.disabled).toBe(true);
  });

  it.each([
    ["ACKNOWLEDGED", "결과와 한계 확인", "확인됨"],
    ["NEEDS_FOLLOW_UP", "추가 확인·조치 필요", "추가 확인·조치 필요"],
  ] as const)("submits %s with a required comment, then refreshes the current review state", async (decision, label, status) => {
    const saved = { ...reviewReceipt(), decision, comment: "이번 주 결과를 확인했습니다." };
    let reads = 0;
    const reviewFetch = vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === "POST") return Promise.resolve(json(saved, 201));
      reads += 1;
      return Promise.resolve(json(reviewPage(reads === 1 ? [] : [saved])));
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(detail())));
    renderPanel({ canCreate: true }, reviewFetch);

    await screen.findByText("미검토");
    fireEvent.click(screen.getByLabelText(label));
    fireEvent.change(screen.getByLabelText(/검토 의견/), { target: { value: saved.comment } });
    expect((screen.getByRole("button", { name: "검토 기록 추가" }) as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "검토 기록 추가" }));

    expect(await screen.findByText(status, { selector: "span" })).toBeTruthy();
    expect(screen.getByText("검토 기록을 저장하고 최신 상태를 다시 불러왔습니다.")).toBeTruthy();
    const post = reviewFetch.mock.calls.find(([, init]) => init?.method === "POST");
    expect(post?.[0]).toBe("/api/sites/site-1/analyses/analysis-1/reviews");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ decision, comment: saved.comment });
    expect(post?.[1]?.headers).not.toHaveProperty("Idempotency-Key");
    expect(reviewFetch).toHaveBeenCalledTimes(3);
  });

  it.each([
    [403, "검토 기록에는 현장 쓰기 권한이 필요합니다.", null],
    [409, "변화 분석 기록이 갱신되었습니다. 상세를 다시 불러온 뒤 검토하세요.", "변화 분석 상세 다시 불러오기"],
  ] as const)("guides review permission/conflict status %s", async (status, message, refreshAction) => {
    const reviewFetch = vi.fn((_url: string, init?: RequestInit) => Promise.resolve(init?.method === "POST"
      ? json({ message: "server message" }, status)
      : json(reviewPage())));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(detail())));
    renderPanel({ canCreate: true }, reviewFetch);

    await screen.findByText("미검토");
    fireEvent.click(screen.getByLabelText("결과와 한계 확인"));
    fireEvent.change(screen.getByLabelText(/검토 의견/), { target: { value: "검토했습니다." } });
    fireEvent.click(screen.getByRole("button", { name: "검토 기록 추가" }));

    expect(await screen.findByText(new RegExp(message))).toBeTruthy();
    if (refreshAction) expect(screen.getByRole("button", { name: refreshAction })).toBeTruthy();
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
    fireEvent.click(screen.getByRole("button", { name: "변화 분석 요청" }));
    await screen.findByText("요청을 다시 시도하세요.");
    fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    const [firstUrl, firstInit] = fetchMock.mock.calls[0]!;
    const [secondUrl, secondInit] = fetchMock.mock.calls[1]!;
    expect(firstUrl).toBe("/api/sites/site-1/work-areas/area-1/analyses");
    expect(secondUrl).toBe(firstUrl);
    expect(JSON.parse(firstInit.body)).toEqual({ baseline: observations[0]!.selector, current: observations[1]!.selector });
    expect(secondInit.headers["Idempotency-Key"]).toBe(firstInit.headers["Idempotency-Key"]);
    expect(screen.getByText("분석 ID · analysis-created")).toBeTruthy();
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
    fireEvent.click(screen.getByRole("button", { name: "변화 분석 요청" }));
    const message = await screen.findByText(new RegExp(code === "ANALYSIS_ACTIVATION_UNAVAILABLE" ? "이 환경에서는 변화 분석 실행이 활성화되어 있지 않아" : "변화 분석 실행 활성화가 만료되어"));
    expect(message.textContent).toContain("관리자");
    expect(screen.getByText("보류된 요청은 변화 분석 실행 활성화가 복구되기 전에는 처리되지 않습니다. 활성화 상태가 확인된 뒤 다시 시도하거나 보류 요청을 취소하세요.")).toBeTruthy();

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
    fireEvent.click(screen.getByRole("button", { name: "변화 분석 요청" }));
    await screen.findByText(/이 환경에서는 변화 분석 실행이 활성화되어 있지 않아/);

    const stored = JSON.parse(sessionStorage.getItem("ksi.analysis.pending.v2:org-1:operator-1:site-1") ?? "null");
    expect(stored.version).toBe(2);
    expect(stored.attempt.activationBlockCode).toBe(code);
    firstRender.unmount();

    renderPanel(props);
    await screen.findByText(/이 환경에서는 변화 분석 실행이 활성화되어 있지 않아/);
    expect(screen.getByText("보류된 요청은 변화 분석 실행 활성화가 복구되기 전에는 처리되지 않습니다. 활성화 상태가 확인된 뒤 다시 시도하거나 보류 요청을 취소하세요.")).toBeTruthy();
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
    fireEvent.click(screen.getByRole("button", { name: "변화 분석 요청" }));
    await screen.findByText("요청을 다시 시도하세요.");

    const stored = JSON.parse(sessionStorage.getItem("ksi.analysis.pending.v2:org-1:operator-1:site-1") ?? "null");
    expect(stored.version).toBe(2);
    expect(stored.attempt.activationBlockCode).toBeNull();
    firstRender.unmount();

    renderPanel(props);
    expect(await screen.findByText("중단된 요청이 있습니다. 다시 시도하면 같은 요청 식별자로 Core에 확인합니다.")).toBeTruthy();
    expect(screen.queryByText(/보류된 요청은 변화 분석 실행 활성화가 복구되기 전에는 처리되지 않습니다/)).toBeNull();
  });

  it.each([
    [401, /세션이 만료되어 요청을 보내지 못했습니다/, true],
    [403, /변화 분석 요청 권한이 없습니다/, false],
    [409, /같은 요청 식별자로 다른 요청이 이미 접수되어 있습니다/, false],
  ] as const)("keeps the pending idempotent attempt and explains submit failure %s without leaking server detail", async (status, message, needsLogin) => {
    const created = detail("analysis-created", "QUEUED");
    created.suitabilityState = "PROVISIONAL_ACCURACY_UNVERIFIED";
    created.result = null;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json({ code: "FORBIDDEN_BY_POLICY", detail: "internal-only" }, status))
      .mockResolvedValueOnce(json(created, 202));
    vi.stubGlobal("fetch", fetchMock);
    renderPanel({ initialPage: listPage([]), initialSelectedDetail: null, initialAnalysisId: null, canCreate: true });

    fireEvent.change(screen.getByLabelText("작업구역"), { target: { value: "area-1" } });
    fireEvent.change(screen.getByLabelText("기준 관측"), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText("현재 관측"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "변화 분석 요청" }));

    expect(await screen.findByText(message)).toBeTruthy();
    // 서버 원문(code·detail)은 그대로 두지 않는다.
    expect(screen.queryByText(/FORBIDDEN_BY_POLICY|internal-only/)).toBeNull();
    if (needsLogin) {
      const login = screen.getByRole("link", { name: "다시 로그인" });
      expect(login.getAttribute("href")).toMatch(/^\/login\?next=/);
    } else {
      expect(screen.queryByRole("link", { name: "다시 로그인" })).toBeNull();
    }
    // 보류 시도는 유지되며 같은 멱등 키로 다시 확인한다.
    expect(screen.getByRole("button", { name: "다시 시도" })).toBeTruthy();
    const stored = JSON.parse(sessionStorage.getItem("ksi.analysis.pending.v2:org-1:operator-1:site-1") ?? "null");
    expect(stored.attempt.key).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1]?.[1]?.headers["Idempotency-Key"]).toBe(fetchMock.mock.calls[0]?.[1]?.headers["Idempotency-Key"]);
    expect(screen.getByText("분석 ID · analysis-created")).toBeTruthy();
  });

  it("blocks new picks while candidate lists are unavailable without claiming an empty area", () => {
    renderPanel({
      canCreate: true,
      initialPage: listPage([]),
      initialSelectedDetail: null,
      initialAnalysisId: null,
      initialWorkAreaId: "area-1",
      listsState: { workAreas: "ready", observations: "unavailable", workOrders: "ready", history: "ready" },
    });

    expect(screen.getByText("목록을 확인할 수 없습니다")).toBeTruthy();
    expect(screen.queryByText("이 구역의 분석 후보가 없습니다")).toBeNull();
    // 선택 폼 대신 목록 상태 블록이 그 자리를 대신한다 — 고를 것이 없으니
    // 선택지 자체를 두지 않는다.
    expect(screen.queryByLabelText("기준 관측")).toBeNull();
    expect(screen.queryByLabelText("현재 관측")).toBeNull();
    expect(screen.queryByRole("button", { name: "변화 분석 요청" })).toBeNull();
    expect(screen.getByRole("button", { name: "목록 다시 불러오기" })).toBeTruthy();

    cleanup();
    renderPanel({
      canCreate: true,
      initialPage: listPage([]),
      initialSelectedDetail: null,
      initialAnalysisId: null,
      listsState: { workAreas: "ready", observations: "unavailable", workOrders: "ready", history: "ready" },
    });
    // 구역을 고르기 전에는 폼이 보이지만 고를 수 없고, 같은 상태 안내가 있다.
    expect(screen.getByText("목록을 확인할 수 없습니다")).toBeTruthy();
    expect((screen.getByLabelText("작업구역") as HTMLSelectElement).disabled).toBe(false);
    expect((screen.getByLabelText("기준 관측") as HTMLSelectElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "변화 분석 요청" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it.each(["denied", "unconfirmed", "unavailable"] as const)("explains %s candidate lists and preserves scoped recovery", (state) => {
    renderPanel({ canCreate: true, initialPage: listPage([]), initialSelectedDetail: null, initialAnalysisId: null,
      initialWorkAreaId: "area-1", listsState: { workAreas: "ready", observations: state, workOrders: "ready", history: "ready" } });
    expect(screen.getByText(state === "denied" ? /관측 목록을 조회할 권한이 없습니다/ : state === "unconfirmed" ? /관측 목록을 확인할 수 없습니다/ : /관측 목록을 불러오지 못했습니다/)).toBeTruthy();
    expect(screen.queryByText("이 구역의 분석 후보가 없습니다")).toBeNull();
    expect(screen.queryByRole("button", { name: "변화 분석 요청" })).toBeNull();
    expect(screen.getByRole("link", { name: "등록 자료와 검사 상태 확인" }).getAttribute("href")).toBe("/sites/site-1/spatial-assets?workAreaId=area-1");
    expect(screen.getByRole("link", { name: "작업공간으로 돌아가기" }).getAttribute("href")).toBe("/sites/site-1?workAreaId=area-1");
    fireEvent.click(screen.getByRole("button", { name: "목록 다시 불러오기" }));
    expect(router.refresh).toHaveBeenCalled();
  });

  it("offers scopeless returns when candidate lists fail before area selection", () => {
    renderPanel({ canCreate: true, initialPage: listPage([]), initialSelectedDetail: null, initialAnalysisId: null,
      initialWorkAreaId: "", listsState: { workAreas: "denied", observations: "ready", workOrders: "ready", history: "ready" } });
    expect(screen.getByText(/작업구역 목록을 조회할 권한이 없습니다/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "등록 자료 보기" }).getAttribute("href")).toBe("/sites/site-1/spatial-assets");
    expect(screen.getByRole("link", { name: "현장 현황 보기" }).getAttribute("href")).toBe("/sites/site-1");
  });

  it("offers scoped exits when history is unconfirmed without asserting empty history", () => {
    renderPanel({ canCreate: false, initialPage: listPage([]), initialSelectedDetail: null, initialAnalysisId: null,
      initialWorkAreaId: "area-1", listsState: { workAreas: "ready", observations: "ready", workOrders: "ready", history: "unconfirmed", historyMessage: "현장 변화 분석 이력을 확인할 수 없습니다. 현장 범위를 확인하거나 다시 불러오세요. 이 안내는 등록 자료의 상태를 판단하지 않습니다." } });
    expect(screen.getByRole("alert").textContent).toContain("등록 자료의 상태를 판단하지 않습니다");
    expect(screen.queryByText(/아직 변화 분석 요청이 없습니다/)).toBeNull();
    expect(screen.getByRole("link", { name: "등록 자료 보기" }).getAttribute("href")).toBe("/sites/site-1/spatial-assets?workAreaId=area-1");
    expect(screen.getByRole("link", { name: "현장 현황 보기" }).getAttribute("href")).toBe("/sites/site-1?workAreaId=area-1");
  });

  it("names the broken attribution link instead of claiming an empty area", () => {
    renderPanel({
      canCreate: true,
      initialPage: listPage([]),
      initialSelectedDetail: null,
      initialAnalysisId: null,
      initialWorkAreaId: "area-1",
      observations: [],
      siteObservations: observations,
      listsState: { workAreas: "ready", observations: "ready", workOrders: "unavailable", history: "ready" },
    });

    // 귀속 끊김은 후보 없음이 아니다 — 어느 연결이 끊겼는지를 밝힌다.
    expect(screen.getByText(/연결 정보를 확인할 수 없어/)).toBeTruthy();
    expect(screen.queryByText("이 구역의 분석 후보가 없습니다")).toBeNull();
    expect(screen.queryByRole("button", { name: "변화 분석 요청" })).toBeNull();
    expect(screen.getByRole("button", { name: "목록 다시 불러오기" })).toBeTruthy();
  });

  it("disables candidate picks with a truthful notice when only attribution is unavailable", () => {
    renderPanel({
      canCreate: true,
      initialPage: listPage([]),
      initialSelectedDetail: null,
      initialAnalysisId: null,
      observations: [],
      siteObservations: observations,
      listsState: { workAreas: "ready", observations: "ready", workOrders: "unavailable", history: "ready" },
    });

    expect(screen.getByText(/연결 정보를 불러오지 못했습니다/)).toBeTruthy();
    expect((screen.getByLabelText("작업구역") as HTMLSelectElement).disabled).toBe(false);
    expect((screen.getByLabelText("기준 관측") as HTMLSelectElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "변화 분석 요청" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByText("이 구역의 분석 후보가 없습니다")).toBeNull();
  });

  it("shows the verified empty message when a failed history recovers empty", async () => {
    const network = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/analyses?")) return json(listPage([]));
      return json(reviewPage());
    });
    vi.stubGlobal("fetch", network);
    renderPanel({
      canCreate: true,
      workAreas: [],
      observations: [],
      initialPage: listPage([]),
      initialSelectedDetail: null,
      initialAnalysisId: null,
      listsState: { workAreas: "ready", observations: "ready", workOrders: "ready", history: "failed", historyMessage: "현장 변화 분석 이력을 불러오지 못했습니다. 다시 불러오면 최신 이력을 확인할 수 있습니다." },
    });

    expect(screen.getByText("분석 이력을 확인할 수 없습니다")).toBeTruthy();
    expect(screen.queryByText(/아직 변화 분석 요청이 없습니다/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "이력 다시 불러오기" }));
    await waitFor(() => expect(screen.queryByText("분석 이력을 확인할 수 없습니다")).toBeNull());
    // 다시 불러와서 읽은 빈 목록은 확인된 빈 이력이다 — 빈 안내를 둔다.
    expect(screen.getByText(/이 현장에는 아직 변화 분석 요청이 없습니다/)).toBeTruthy();
  });

  it("holds the history retry while the server asked to wait", () => {
    renderPanel({
      canCreate: false,
      initialPage: listPage([]),
      initialSelectedDetail: null,
      initialAnalysisId: null,
      listsState: { workAreas: "ready", observations: "ready", workOrders: "ready", history: "failed", historyMessage: "현장 변화 분석 이력을 불러오지 못했습니다.", historyRetryAfterSeconds: 90 },
    });

    const retry = screen.getByRole("button", { name: /초 후 다시 시도/ });
    expect(retry.textContent).toContain("90초 후 다시 시도");
    expect((retry as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows a denied history as record-section state and never an empty-history claim", () => {
    renderPanel({
      canCreate: true,
      initialPage: listPage([]),
      initialSelectedDetail: null,
      initialAnalysisId: null,
      listsState: { workAreas: "ready", observations: "ready", workOrders: "ready", history: "denied", historyMessage: "현장 변화 분석 이력을 조회할 권한이 없습니다. 현장 담당자에게 변화 분석 기록 조회 권한을 요청하세요." },
    });

    expect(screen.getByText("분석 이력을 확인할 수 없습니다")).toBeTruthy();
    expect(screen.getByText(/변화 분석 기록 조회 권한을 요청하세요/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "이력 다시 불러오기" })).toBeNull();
    expect(screen.queryByText(/아직 변화 분석 요청이 없습니다/)).toBeNull();
  });

  it("recovers the history section with a client refetch after a transient history failure", async () => {
    const network = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/analyses?")) return json(listPage(["analysis-1"]));
      if (/\/analyses\/analysis-1$/.test(url)) return json(detail());
      return json(reviewPage());
    });
    vi.stubGlobal("fetch", network);
    renderPanel({
      canCreate: false,
      listsState: { workAreas: "ready", observations: "ready", workOrders: "ready", history: "failed", historyMessage: "현장 변화 분석 이력을 불러오지 못했습니다. 다시 불러오면 최신 이력을 확인할 수 있습니다." },
    });

    expect(screen.getByText("분석 이력을 확인할 수 없습니다")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "이력 다시 불러오기" }));
    await waitFor(() => expect(screen.queryByText("분석 이력을 확인할 수 없습니다")).toBeNull());
    expect(network).toHaveBeenCalled();
  });

  it("offers a list retry from the alert when loading the next history page fails", async () => {
    let fail = true;
    const network = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/analyses?")) return fail ? json({ error: "busy" }, 503) : json(listPage(["analysis-1"]));
      return json(reviewPage());
    });
    vi.stubGlobal("fetch", network);
    renderPanel({ initialPage: listPage([], "older-cursor"), initialSelectedDetail: null, initialAnalysisId: null, canCreate: false });

    fireEvent.click(screen.getByRole("button", { name: "다음 변화 분석 보기" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.queryByText(/현재 페이지에 변화 분석 요청이 없습니다/)).toBeNull();
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "목록 다시 불러오기" }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(screen.getByText("분석 ID · analysis-1")).toBeTruthy();
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
    fireEvent.click(screen.getByRole("button", { name: "다음 변화 분석 보기" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/sites/site-1/analyses/analysis-1",
      "/api/sites/site-1/analyses?limit=50&cursor=list-cursor",
    ]);
    await waitFor(() => expect(document.body.textContent).toContain("analysis-next"));
    expect(fetchMock).toHaveBeenCalledWith("/api/sites/site-1/analyses/analysis-1", expect.objectContaining({ cache: "no-store" }));
    expect(fetchMock).toHaveBeenCalledWith("/api/sites/site-1/analyses?limit=50&cursor=list-cursor", expect.objectContaining({ cache: "no-store" }));
    fireEvent.click(screen.getAllByRole("button", { name: "이 변화 분석 보기" })[1]!);
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

    fireEvent.click(screen.getByRole("button", { name: "다음 변화 분석 보기" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(screen.getByText("분석 ID · analysis-1")).toBeTruthy();

    fireEvent.focus(window);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
    await waitFor(() => expect(screen.queryByText("분석 ID · analysis-50")).toBeNull());
    expect(screen.getByText("분석 ID · analysis-101")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "다음 변화 분석 보기" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(5));
    expect(fetchMock.mock.calls[4]![0]).toBe("/api/sites/site-1/analyses?limit=50&cursor=fresh-cursor");
    await waitFor(() => expect(screen.getByText("분석 ID · analysis-51")).toBeTruthy());
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
    expect(screen.getByLabelText("근거").textContent).toContain("현재 불러온 근거 2개");

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
    await screen.findByText("분석 ID · analysis-old");
    expect(fetchMock).toHaveBeenCalledWith("/api/sites/site-1/analyses/analysis-old", expect.objectContaining({ cache: "no-store" }));
  });

  it("guides viewers in task language without exposing the permission token", () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(detail())));
    const first = renderPanel({ canCreate: false });
    expect(screen.queryByText("변화 분석 기록을 조회할 수 있습니다.")).toBeNull();
    const blocked = screen.getByRole("button", { name: "새 변화 분석 요청" });
    expect(blocked.hasAttribute("disabled")).toBe(false);
    fireEvent.click(blocked);
    expect(screen.getByText(/새 변화 분석 요청은 권한 있는 현장 담당자가 진행해야 합니다/)).toBeTruthy();
    expect(document.body.textContent).not.toContain("SITES_WRITE");
    first.unmount();

    const failed = { ...detail(), executionState: "FAILED" as const, suitabilityState: "REASSESSMENT_REQUIRED" as const, result: null };
    const page = listPage(["analysis-1"]);
    page.items[0] = { ...page.items[0]!, executionState: "FAILED", suitabilityState: "REASSESSMENT_REQUIRED", resultId: null, metrics: null };
    renderPanel({ initialPage: page, initialSelectedDetail: failed, canCreate: false });
    expect(screen.getByText("Core가 변화 분석을 완료하지 못했습니다. 현장 변화 분석 담당자에게 실패 사유와 근거 검토를 요청하세요.")).toBeTruthy();
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

describe("newer observation notice", () => {
  const newerObservation: AnalysisObservationOption & { workAreaIds: string[] } = {
    selector: selector("work-newer", "c"),
    observationEpochId: "epoch-newer",
    captureStartedAt: "2026-09-15T00:00:00Z",
    captureEndedAt: "2026-09-15T00:30:00Z",
    workAreaIds: ["area-1"],
  };
  const observationsWithNewer = [...observations, newerObservation];

  function newerDetail(analysisId = "analysis-new"): AnalysisView {
    return {
      ...detail(analysisId),
      baseline: observations[1]!.selector,
      current: newerObservation.selector,
      createdAt: "2026-09-15T01:00:00Z",
    };
  }

  function stubDetailFetch(known: Record<string, AnalysisView>) {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (/\/reviews(?:\?|$)/.test(url)) return Promise.resolve(json(reviewPage()));
      const match = url.match(/\/analyses\/([^\/?]+)/);
      const found = match?.[1] ? known[match[1]] : undefined;
      if (found) return Promise.resolve(json(found));
      return Promise.resolve(json(detail()));
    }));
  }

  it("states a newer observation plainly when its analysis has no loaded result", () => {
    stubDetailFetch({ "analysis-1": detail() });
    renderPanel({
      observations: observationsWithNewer,
      initialPage: listPage(["analysis-1", "analysis-new"]),
      initialSelectedDetail: detail(),
      initialAnalysisId: "analysis-1",
    });

    const selected = within(screen.getByText("분석 ID · analysis-1").closest("article")!);
    expect(selected.getByText(/이 작업구역에 더 새 관측이 있습니다/)).toBeTruthy();
    expect(selected.getByText(/새 관측 시각 2026\. 9\. 15\. 09:30/)).toBeTruthy();
    expect(selected.getByText(/2026\. 9\. 8\. 09:30 관측 기준 기록/)).toBeTruthy();
    expect(selected.getByText(/새 관측에 대한 분석 결과는 아직 없습니다/)).toBeTruthy();
    expect(selected.queryByRole("link", { name: "새 분석 결과 보기" })).toBeNull();
    expect(selected.queryByText(/대체됨|구버전/)).toBeNull();
    // 이전 결과의 수치·적합성은 알림과 무관하게 그대로 둔다.
    expect(selected.getByText("12 m³")).toBeTruthy();
    expect(selected.getByText("정확도 미확인")).toBeTruthy();
  });

  it("links to the newer analysis only when its result was actually loaded", async () => {
    const older = detail("analysis-1");
    stubDetailFetch({ "analysis-1": older, "analysis-new": newerDetail() });
    renderPanel({
      observations: observationsWithNewer,
      initialPage: listPage(["analysis-new", "analysis-1"]),
      initialSelectedDetail: newerDetail(),
      initialAnalysisId: "analysis-new",
    });

    // 가장 새 분석에는 알림이 없다.
    expect(screen.queryByText(/이 작업구역에 더 새 관측이 있습니다/)).toBeNull();

    fireEvent.click(screen.getAllByRole("button", { name: "이 변화 분석 보기" })[1]!);
    const notice = await screen.findByText(/이 작업구역에 더 새 관측이 있습니다/);
    const olderCard = within(notice.closest("article")!);
    const link = olderCard.getByRole("link", { name: "새 분석 결과 보기" });
    expect(link.getAttribute("href")).toBe("/sites/site-1/analysis?analysisId=analysis-new");
    expect(notice.textContent).toContain("2026. 9. 15. 09:30");
    expect(notice.textContent).not.toContain("대체됨");
    expect(notice.textContent).not.toContain("구버전");
    expect(screen.getAllByText(/이 작업구역에 더 새 관측이 있습니다/)).toHaveLength(1);
  });

  it("finds the result epoch site-wide when it is not attributed to the area", () => {
    // 실제 재현 귀속(F-03): 결과의 현재 epoch(epoch-current)은 구역 귀속
    // 목록에 없고, 같은 구역에는 더 늦은 관측(epoch-newer)이 있다.
    // 귀속 목록만으로는 시각을 알 수 없으므로 Site 범위 목록에서 찾는다.
    const siteScoped = observationsWithNewer.map(({ selector, observationEpochId, captureStartedAt, captureEndedAt }) => ({
      selector,
      observationEpochId,
      captureStartedAt,
      captureEndedAt,
    }));
    const areaNewerOnly = observationsWithNewer.filter(
      (option) => option.observationEpochId === "epoch-newer",
    );
    stubDetailFetch({ "analysis-1": detail() });
    renderPanel({
      observations: areaNewerOnly,
      siteObservations: siteScoped,
      initialPage: listPage(["analysis-1"]),
      initialSelectedDetail: detail(),
      initialAnalysisId: "analysis-1",
    });

    const selected = within(screen.getByText("분석 ID · analysis-1").closest("article")!);
    expect(selected.getByText(/이 작업구역에 더 새 관측이 있습니다/)).toBeTruthy();
    expect(selected.getByText(/새 관측 시각 2026\. 9\. 15\. 09:30/)).toBeTruthy();
    expect(selected.getByText(/2026\. 9\. 8\. 09:30 관측 기준 기록/)).toBeTruthy();
    expect(selected.getByText(/새 관측에 대한 분석 결과는 아직 없습니다/)).toBeTruthy();
    expect(selected.queryByText(/대체됨|구버전/)).toBeNull();
  });

  it("shows nothing when the result epoch is absent from the site-wide list", () => {
    const areaNewerOnly = observationsWithNewer.filter(
      (option) => option.observationEpochId === "epoch-newer",
    );
    stubDetailFetch({ "analysis-1": detail() });
    renderPanel({
      observations: areaNewerOnly,
      siteObservations: [],
      initialPage: listPage(["analysis-1"]),
      initialSelectedDetail: detail(),
      initialAnalysisId: "analysis-1",
    });

    expect(screen.queryByText(/이 작업구역에 더 새 관측이 있습니다/)).toBeNull();
  });

  it("shows no empty required selects when the area has zero candidates", () => {
    vi.stubGlobal("fetch", vi.fn());
    renderPanel({ canCreate: true, initialAnalysisId: null, initialSelectedDetail: null,
      initialPage: listPage([]), observations: [], siteObservations: [], initialWorkAreaId: "area-1" });
    // 빈 선택지를 요구 조건처럼 두지 않는다.
    expect(screen.getByText("이 구역의 분석 후보가 없습니다")).toBeTruthy();
    expect(screen.queryByLabelText("기준 관측")).toBeNull();
    expect(screen.queryByLabelText("현재 관측")).toBeNull();
    expect(screen.queryByRole("button", { name: "변화 분석 요청" })).toBeNull();
    // 실제 다음 행동을 둔다.
    expect(screen.getByRole("link", { name: "등록 자료와 검사 상태 확인" }).getAttribute("href"))
      .toBe("/sites/site-1/spatial-assets?workAreaId=area-1");
    expect(screen.getByRole("link", { name: "작업공간으로 돌아가기" }).getAttribute("href"))
      .toBe("/sites/site-1?workAreaId=area-1");
  });

  it("names the brought pair without preselecting it when candidates are empty", () => {
    vi.stubGlobal("fetch", vi.fn());
    const brought = {
      baseline: selector("work-baseline", "a"), baselineMatched: false,
      current: selector("work-current", "b"), currentMatched: false,
    };
    renderPanel({ canCreate: true, initialAnalysisId: null, initialSelectedDetail: null,
      initialPage: listPage([]), observations: [], siteObservations: [], initialWorkAreaId: "area-1",
      broughtSelectors: brought, visualReturnHref: "/sites/site-1?mode=compare&workAreaId=area-1" });
    expect(screen.getByText(/가져온 쌍 · 후보 목록에 없어 미리 고르지 않았습니다/)).toBeTruthy();
    expect(screen.getByText(/관측이 부적합하다는 판정이 아닙니다/)).toBeTruthy();
    expect(screen.queryByLabelText("기준 관측")).toBeNull();
    expect(screen.getByRole("link", { name: "독립 보기로 돌아가기" })).toBeTruthy();
  });

  it("states an exact-selector miss instead of a suitability verdict when candidates are empty", () => {
    vi.stubGlobal("fetch", vi.fn());
    renderPanel({ canCreate: true, initialAnalysisId: null, initialSelectedDetail: null,
      initialPage: listPage([]), observations: [], siteObservations: [], initialWorkAreaId: "area-1" });
    expect(screen.getByText(/요청 입력과 정확히 맞는 분석 후보가 없습니다/)).toBeTruthy();
    // 후보 목록의 선택자 일치 여부만 말하며, 관측의 적합성을 판정하지 않는다.
    expect(screen.queryByText(/분석 가능 관측/)).toBeNull();
    expect(screen.getByText(/관측이 부적합하다는 판정이 아닙니다/)).toBeTruthy();
  });

  it("keeps unverified brought identifiers out of trusted display until disclosed", () => {
    vi.stubGlobal("fetch", vi.fn());
    const brought = {
      baseline: selector("work-foreign", "a"), baselineMatched: false,
      current: selector("work-current", "b"), currentMatched: false,
    };
    // work-current만 이 현장·조직 범위의 작업명으로 확인된다.
    renderPanel({ canCreate: true, initialAnalysisId: null, initialSelectedDetail: null,
      initialPage: listPage([]), observations: [], siteObservations: [], initialWorkAreaId: "area-1",
      workOrderNames: { "work-current": "현재 작업" },
      broughtSelectors: brought, visualReturnHref: "/sites/site-1?mode=compare&workAreaId=area-1" });
    // 범위에서 확인한 이름만 밝히고, 모르는 작업명은 단정하지 않는다.
    expect(screen.getByText(/현재 작업 · 버전 1/)).toBeTruthy();
    expect(screen.getByText(/작업명 확인 불가 · 버전 1/)).toBeTruthy();
    // 원문 식별자는 1차 표시가 아니라 펼침에만 둔다.
    const disclosures = screen.getAllByText("가져온 값(검증되지 않음) 확인");
    expect(disclosures).toHaveLength(2);
    expect(disclosures[0]!.closest("details")?.hasAttribute("open")).toBe(false);
    expect(screen.queryByText("work-foreign")).toBeNull();
    fireEvent.click(disclosures[0]!);
    expect(disclosures[0]!.closest("details")?.textContent).toContain(selector("work-foreign", "a").submissionRef);
    expect(disclosures[0]!.closest("details")?.textContent).toContain("이 현장·조직 범위에서 작업명을 확인하지 못했습니다");
  });
});

describe("analysis readiness check", () => {
  const digest = `sha256:${"e".repeat(64)}`;
  const readinessView = {
    contractVersion: "analysis-readiness.v1",
    siteId: "site-1",
    workAreaId: "area-1",
    baseline: selector("work-baseline", "a"),
    current: selector("work-current", "b"),
    suitabilityState: "EVALUATED",
    blockers: [],
    limitationCodes: ["PROVISIONAL_ACCURACY_UNVERIFIED"],
    checkedAt: "2026-10-20T00:00:00Z",
    calculationIdentityDigest: digest,
    coverageCheck: "REQUIRES_WORKER_VALIDATION",
  };

  function stubReadinessFetch(responder: (url: string) => Response) {
    const readinessBodies: unknown[] = [];
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (/\/reviews(?:\?|$)/.test(url)) return Promise.resolve(json(reviewPage()));
      if (url.includes("/analysis-readiness")) {
        readinessBodies.push(init?.body);
        return Promise.resolve(responder(url));
      }
      return Promise.resolve(json(detail()));
    });
    vi.stubGlobal("fetch", fetchMock);
    return { fetchMock, readinessBodies };
  }

  function renderReadyToCheck() {
    renderPanel({ canCreate: true, initialAnalysisId: null, initialSelectedDetail: null,
      initialPage: listPage([]), initialWorkAreaId: "area-1" });
    fireEvent.change(screen.getByLabelText("기준 관측"), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText("현재 관측"), { target: { value: "1" } });
  }

  function readinessCalls(stub: { fetchMock: ReturnType<typeof vi.fn> }) {
    return stub.fetchMock.mock.calls.map(([input]) => (typeof input === "string" ? input : String(input)))
      .filter((url) => url.includes("/analysis-readiness"));
  }

  it("sends no readiness request on view or selection alone", () => {
    const fetchMock = stubReadinessFetch(() => json(readinessView));
    renderReadyToCheck();
    // 쌍을 고르기 전에도, 고른 뒤에도 화면 진입·선택만으로는 전송하지 않는다.
    expect(readinessCalls(fetchMock)).toHaveLength(0);
    expect(screen.getByRole("button", { name: "선택한 쌍의 분석 조건 확인" })).toBeTruthy();
  });

  it("shows the checked suitability, blockers and limits, then invalidates on pair change", async () => {
    const blocked = {
      ...readinessView,
      suitabilityState: "BLOCKED",
      limitationCodes: [],
      blockers: [{ code: "VERTICAL_REFERENCE_MISMATCH", epoch: "CURRENT", evidenceRef: null, detail: null }],
    };
    const stubbed = stubReadinessFetch(() => json(blocked));
    renderReadyToCheck();
    fireEvent.click(screen.getByRole("button", { name: "선택한 쌍의 분석 조건 확인" }));
    expect(await screen.findByText("조건 확인 · 차단됨")).toBeTruthy();
    expect(screen.getByText("높이 기준이 서로 다름 · 현재 관측")).toBeTruthy();
    expect(screen.getByText(/공통 유효 범위는 계산 과정에서 확인합니다/)).toBeTruthy();
    expect(screen.getByText(/이 확인은 요청 권한을 주지 않습니다/)).toBeTruthy();
    // 계산 식별 확인값은 펼침에만 둔다.
    const recordValues = screen.getByText("확인 기록 값 보기").closest("details")!;
    expect(recordValues.hasAttribute("open")).toBe(false);
    fireEvent.click(screen.getByText("확인 기록 값 보기"));
    expect(recordValues.textContent).toContain(digest);
    expect(readinessCalls(stubbed)).toHaveLength(1);
    // 쌍이 바뀌면 확인 결과를 버리고 진행 중 확인을 취소한다.
    fireEvent.change(screen.getByLabelText("현재 관측"), { target: { value: "" } });
    expect(screen.queryByText("조건 확인 · 차단됨")).toBeNull();
    expect(screen.queryByRole("button", { name: "선택한 쌍의 분석 조건 확인" })).toBeNull();
    expect(JSON.parse(String(stubbed.readinessBodies[0])))
      .toEqual({ baseline: observations[0]!.selector, current: observations[1]!.selector });
    expect(screen.getByText(/고르면 조건 확인을 실행할 수 있습니다/)).toBeTruthy();
  });

  it("fails closed with distinct copy for denial, unsupported environments and server errors", async () => {
    const fetchMock = stubReadinessFetch(() => json({ message: "denied" }, 403));
    renderReadyToCheck();
    fireEvent.click(screen.getByRole("button", { name: "선택한 쌍의 분석 조건 확인" }));
    expect(await screen.findByText(/분석 조건 확인을 조회할 권한이 없습니다/)).toBeTruthy();
    expect(screen.queryByText(/조건 확인 ·/)).toBeNull();
    // 권한이 복구되면 같은 자리에서 다시 확인할 수 있다(쌍을 바꾸지 않아도 된다).
    expect(screen.getByRole("button", { name: "다시 확인" })).toBeTruthy();
    expect(readinessCalls(fetchMock)).toHaveLength(1);

    cleanup();
    stubReadinessFetch(() => json({ message: "no route" }, 404));
    renderReadyToCheck();
    fireEvent.click(screen.getByRole("button", { name: "선택한 쌍의 분석 조건 확인" }));
    expect(await screen.findByText(/이 환경에서는 분석 조건 확인을 지원하지 않습니다/)).toBeTruthy();
    expect(screen.getByText(/확인할 수 없는 조건을 적합하다고 보지 않습니다/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "등록 자료와 검사 상태 확인" })).toBeTruthy();
    expect(screen.queryByText(/조건 확인 ·/)).toBeNull();

    cleanup();
    const retryMock = stubReadinessFetch(() => json({ message: "boom" }, 500));
    renderReadyToCheck();
    fireEvent.click(screen.getByRole("button", { name: "선택한 쌍의 분석 조건 확인" }));
    expect(await screen.findByText(/분석 조건 확인을 마치지 못했습니다/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "다시 확인" })).toBeTruthy();
    expect(readinessCalls(retryMock)).toHaveLength(1);
  });

  it("keeps the readiness read outside the desktop-only write gate", () => {
    stubReadinessFetch(() => json(readinessView));
    renderReadyToCheck();
    const checkButton = screen.getByRole("button", { name: "선택한 쌍의 분석 조건 확인" });
    // 조건 확인(읽기)은 쓰기 경계의 hidden 포장 밖에 둔다 — 작은 화면에서도
    // 볼 수 있고, 요청 제출(쓰기)은 그 안에 둔다.
    expect(checkButton.closest("div.hidden")).toBeNull();
    const submitButton = screen.getByRole("button", { name: "변화 분석 요청", hidden: true });
    expect(submitButton.closest("div.hidden")).not.toBeNull();
    expect(screen.getByText(/읽기 전용이며 권한을 주지 않고/)).toBeTruthy();
  });

  it("inspects a catalog-resolved pair read-only when execution candidates are empty", async () => {
    const pair = {
      workAreaId: "area-1",
      a: { assetRef: `ksa-v1-${"a".repeat(64)}`, selector: selector("work-baseline", "a"), kind: "dsm",
        captureStartedAt: "2026-09-01T00:00:00Z", captureEndedAt: "2026-09-01T00:30:00Z", captureDate: null,
        revision: 1, declaredFileName: "a.tif", verticalIdentifier: "KNGEO2002", verticalBasis: "geoid", inspectionOutcome: "MEASURED" },
      b: { assetRef: `ksa-v1-${"b".repeat(64)}`, selector: selector("work-current", "b"), kind: "dsm",
        captureStartedAt: "2026-09-08T00:00:00Z", captureEndedAt: "2026-09-08T00:30:00Z", captureDate: null,
        revision: 1, declaredFileName: "b.tif", verticalIdentifier: null, verticalBasis: null, inspectionOutcome: "MEASURED" },
    };
    const catalogReadiness = {
      contractVersion: "analysis-readiness.v1",
      siteId: "site-1",
      workAreaId: "area-1",
      baseline: pair.a.selector,
      current: pair.b.selector,
      suitabilityState: "EVALUATED",
      blockers: [],
      limitationCodes: [],
      checkedAt: "2026-10-20T00:00:00Z",
      calculationIdentityDigest: null,
      coverageCheck: "REQUIRES_WORKER_VALIDATION",
    };
    const bodies: unknown[] = [];
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (/\/reviews(?:\?|$)/.test(url)) return Promise.resolve(json(reviewPage()));
      if (url.includes("/analysis-readiness")) {
        bodies.push(init?.body);
        return Promise.resolve(json(catalogReadiness));
      }
      return Promise.resolve(json(detail()));
    }));
    renderPanel({ canCreate: true, initialAnalysisId: null, initialSelectedDetail: null,
      initialPage: listPage([]), observations: [], siteObservations: [], initialWorkAreaId: "area-1",
      catalogPair: pair,
      visualContext: { workAreaId: "area-1", visualAAssetRef: pair.a.assetRef, visualBAssetRef: pair.b.assetRef },
      visualReturnHref: "/sites/site-1?mode=compare&workAreaId=area-1" });
    // 실행은 열지 않고, 카탈로그 사실로 조건만 확인한다.
    expect(screen.getByText("가져온 쌍의 조건 확인")).toBeTruthy();
    expect(screen.getByText(/정확히 맞지 않아 요청할 수 없습니다/)).toBeTruthy();
    expect(screen.queryByLabelText("기준 관측")).toBeNull();
    expect(screen.queryByRole("button", { name: "변화 분석 요청" })).toBeNull();
    expect(screen.getByText(/2026. 9. 1./)).toBeTruthy();
    expect(screen.getByText(/수직 기준 · KNGEO2002/)).toBeTruthy();
    expect(screen.getByText(/수직 기준 확인 불가/)).toBeTruthy();
    expect(screen.queryByText(pair.a.selector.submissionRef)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "선택한 쌍의 분석 조건 확인" }));
    expect(await screen.findByText("조건 확인 · 평가 근거 있음")).toBeTruthy();
    expect(bodies).toHaveLength(1);
    expect(JSON.parse(String(bodies[0]))).toEqual({ baseline: pair.a.selector, current: pair.b.selector });
  });

  it("keeps execution closed for an identical-submission catalog pair", () => {
    const side = { assetRef: `ksa-v1-${"a".repeat(64)}`, selector: selector("work-same", "a"), kind: "dsm",
      captureStartedAt: "2026-09-01T00:00:00Z", captureEndedAt: "2026-09-01T00:30:00Z", captureDate: null,
      revision: 1, declaredFileName: "a.tif", verticalIdentifier: null, verticalBasis: null, inspectionOutcome: "MEASURED" };
    vi.stubGlobal("fetch", vi.fn());
    renderPanel({ canCreate: true, initialAnalysisId: null, initialSelectedDetail: null,
      initialPage: listPage([]), observations: [], siteObservations: [], initialWorkAreaId: "area-1",
      catalogPair: { workAreaId: "area-1", a: side, b: { ...side, assetRef: `ksa-v1-${"b".repeat(64)}`, declaredFileName: "b.tif" } },
      visualContext: { workAreaId: "area-1", visualAAssetRef: side.assetRef, visualBAssetRef: `ksa-v1-${"b".repeat(64)}` },
      visualReturnHref: "/sites/site-1?mode=compare&workAreaId=area-1" });
    expect(screen.getByText(/두 칸이 같은 제출 묶음·버전입니다/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "선택한 쌍의 분석 조건 확인" })).toBeNull();
    expect(screen.queryByRole("button", { name: "변화 분석 요청" })).toBeNull();
  });

  it("offers a genuine re-login path on session expiry instead of an endless retry", async () => {
    stubReadinessFetch(() => json({ message: "expired" }, 401));
    renderReadyToCheck();
    fireEvent.click(screen.getByRole("button", { name: "선택한 쌍의 분석 조건 확인" }));
    expect(await screen.findByText(/세션이 만료되어 조건 확인을 마치지 못했습니다/)).toBeTruthy();
    const login = screen.getByRole("link", { name: "다시 로그인" });
    expect(login.getAttribute("href")).toMatch(/^\/login\?next=/);
    // 원문 쿼리를 그대로 믿지 않고 같은 출처 경로만 싣는다.
    expect(login.getAttribute("href")).not.toContain("http");
    expect(screen.queryByRole("button", { name: "다시 확인" })).toBeNull();
  });

  it("fails closed on an echoed pair that does not match the request", async () => {
    const mismatched = {
      ...readinessView,
      suitabilityState: "EVALUATED",
      blockers: [],
      limitationCodes: [],
      current: selector("work-other", "c"),
    };
    stubReadinessFetch(() => json(mismatched));
    renderReadyToCheck();
    fireEvent.click(screen.getByRole("button", { name: "선택한 쌍의 분석 조건 확인" }));
    expect(await screen.findByText(/분석 조건 확인을 마치지 못했습니다/)).toBeTruthy();
    expect(screen.queryByText(/조건 확인 ·/)).toBeNull();
  });

  it("moves focus to the result after an explicit check and never on pair change", async () => {
    stubReadinessFetch(() => json({ message: "denied" }, 403));
    renderReadyToCheck();
    fireEvent.click(screen.getByRole("button", { name: "선택한 쌍의 분석 조건 확인" }));
    const denied = await screen.findByText(/분석 조건 확인을 조회할 권한이 없습니다/);
    expect(document.activeElement).toBe(denied);
    // 쌍이 바뀌면 확인 결과를 버릴 뿐 초점을 뺏지 않는다.
    fireEvent.change(screen.getByLabelText("현재 관측"), { target: { value: "" } });
    expect(screen.queryByText(/분석 조건 확인을 조회할 권한이 없습니다/)).toBeNull();
    expect(document.activeElement).not.toBe(denied);
    expect(screen.getByText(/고르면 조건 확인을 실행할 수 있습니다/)).toBeTruthy();
  });

  it("states the accuracy limit beside a successful condition check", async () => {
    const cleanEvaluated = { ...readinessView, suitabilityState: "EVALUATED", blockers: [], limitationCodes: [] };
    stubReadinessFetch(() => json(cleanEvaluated));
    renderReadyToCheck();
    fireEvent.click(screen.getByRole("button", { name: "선택한 쌍의 분석 조건 확인" }));
    expect(await screen.findByText("조건 확인 · 평가 근거 있음")).toBeTruthy();
    expect(screen.getByText(/이 확인은 물량 정확도 보증, 측량 승인 또는 정산 사용 승인을 뜻하지 않습니다/)).toBeTruthy();
  });

  it("lets a read-only viewer check a picked pair without any write control", async () => {
    const posted: Array<{ url: string; method: string | undefined }> = [];
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (/\/reviews(?:\?|$)/.test(url)) return Promise.resolve(json(reviewPage()));
      posted.push({ url, method: init?.method });
      if (url.includes("/analysis-readiness")) return Promise.resolve(json({ ...readinessView, suitabilityState: "EVALUATED", blockers: [], limitationCodes: [] }));
      return Promise.resolve(json(detail()));
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPanel({ canCreate: false, initialAnalysisId: null, initialSelectedDetail: null,
      initialPage: listPage([]), initialWorkAreaId: "area-1" });
    // 읽기 권한의 선택·조건 확인은 열려 있다.
    fireEvent.change(screen.getByLabelText("기준 관측"), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText("현재 관측"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "선택한 쌍의 분석 조건 확인" }));
    expect(await screen.findByText("조건 확인 · 평가 근거 있음")).toBeTruthy();
    expect(posted.some(({ url }) => url.includes("/analysis-readiness"))).toBe(true);
    // 실행(생성·재시도·취소)은 두지 않으며, 쓰기 요청을 보내지 않는다.
    expect(screen.queryByRole("button", { name: "변화 분석 요청" })).toBeNull();
    expect(screen.queryByRole("button", { name: "다시 시도" })).toBeNull();
    expect(screen.queryByRole("button", { name: "보류 요청 취소" })).toBeNull();
    expect(screen.getByText(/변화 분석 요청 제출은 현장 쓰기 권한이 있는 담당자에게 요청하세요/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "새 변화 분석 요청" })).toBeTruthy();
    expect(posted.filter(({ url, method }) => method === "POST" && /\/analyses$/.test(url))).toHaveLength(0);
  });

  it("inspects a date-only catalog pair even when unrelated executable candidates exist", async () => {
    // 같은 구역에 실행 후보(정확한 제출 2건)가 있지만, 가져온 쌍은 날짜만
    // 아는 등록 자료라 후보와 정확히 맞지 않는다.
    const dateOnlyPair = {
      workAreaId: "area-1",
      a: { assetRef: `ksa-v1-${"a".repeat(64)}`, selector: selector("work-date-a", "e"), kind: "dsm",
        captureStartedAt: null, captureEndedAt: null, captureDate: "2026-09-01",
        revision: 1, declaredFileName: "date-a.tif", verticalIdentifier: null, verticalBasis: null, inspectionOutcome: "MEASURED" },
      b: { assetRef: `ksa-v1-${"b".repeat(64)}`, selector: selector("work-date-b", "f"), kind: "dsm",
        captureStartedAt: null, captureEndedAt: null, captureDate: "2026-09-08",
        revision: 1, declaredFileName: "date-b.tif", verticalIdentifier: null, verticalBasis: null, inspectionOutcome: "MEASURED" },
    };
    const bodies: unknown[] = [];
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (/\/reviews(?:\?|$)/.test(url)) return Promise.resolve(json(reviewPage()));
      if (url.includes("/analysis-readiness")) {
        bodies.push(init?.body);
        return Promise.resolve(json({ ...readinessView, suitabilityState: "EVALUATED", blockers: [], limitationCodes: [],
          baseline: dateOnlyPair.a.selector, current: dateOnlyPair.b.selector }));
      }
      return Promise.resolve(json(detail()));
    }));
    renderPanel({ canCreate: true, initialAnalysisId: null, initialSelectedDetail: null,
      initialPage: listPage([]), initialWorkAreaId: "area-1",
      catalogPair: dateOnlyPair,
      visualContext: { workAreaId: "area-1", visualAAssetRef: dateOnlyPair.a.assetRef, visualBAssetRef: dateOnlyPair.b.assetRef },
      visualReturnHref: "/sites/site-1?mode=compare&workAreaId=area-1" });
    // 실행 후보 목록과 무관하게 가져온 쌍의 검사가 열린다.
    expect(screen.getByText("가져온 쌍의 조건 확인")).toBeTruthy();
    expect(screen.getAllByText(/날짜만 확인/)).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "선택한 쌍의 분석 조건 확인" }));
    expect(await screen.findByText("조건 확인 · 평가 근거 있음")).toBeTruthy();
    expect(bodies).toHaveLength(1);
    // 조건 확인은 가져온 쌍의 선택자를 그대로 싣는다(후보 대체 없음).
    expect(JSON.parse(String(bodies[0]))).toEqual({ baseline: dateOnlyPair.a.selector, current: dateOnlyPair.b.selector });
    // 다른 실행 후보 쌍은 분리된 라벨 아래에서 직접 고른다.
    expect(screen.getByText(/다른 분석 후보 쌍 선택/)).toBeTruthy();
    expect(screen.getByLabelText("기준 관측")).toBeTruthy();
    // 가져온 쌍을 미리 고르거나 요청 입력으로 쓰지 않는다.
    expect((screen.getByLabelText("기준 관측") as HTMLSelectElement).value).toBe("");
  });

  it("does not duplicate controls when the incoming pair is already executable", () => {
    const matched = {
      workAreaId: "area-1",
      a: { assetRef: `ksa-v1-${"a".repeat(64)}`, selector: selector("work-baseline", "a"), kind: "dsm",
        captureStartedAt: "2026-09-01T00:00:00Z", captureEndedAt: "2026-09-01T00:30:00Z", captureDate: null,
        revision: 1, declaredFileName: "a.tif", verticalIdentifier: null, verticalBasis: null, inspectionOutcome: "MEASURED" },
      b: { assetRef: `ksa-v1-${"b".repeat(64)}`, selector: selector("work-current", "b"), kind: "dsm",
        captureStartedAt: "2026-09-08T00:00:00Z", captureEndedAt: "2026-09-08T00:30:00Z", captureDate: null,
        revision: 1, declaredFileName: "b.tif", verticalIdentifier: null, verticalBasis: null, inspectionOutcome: "MEASURED" },
    };
    vi.stubGlobal("fetch", vi.fn());
    renderPanel({ canCreate: true, initialAnalysisId: null, initialSelectedDetail: null,
      initialPage: listPage([]), initialWorkAreaId: "area-1",
      catalogPair: matched,
      visualContext: { workAreaId: "area-1", visualAAssetRef: matched.a.assetRef, visualBAssetRef: matched.b.assetRef },
      visualReturnHref: "/sites/site-1?mode=compare&workAreaId=area-1" });
    // 정확히 겹치는 쌍은 폼 하나로 충분하므로 검사 블록을 두지 않는다.
    expect(screen.queryByText("가져온 쌍의 조건 확인")).toBeNull();
    expect(screen.queryByText(/다른 분석 후보 쌍 선택/)).toBeNull();
    expect(screen.getByLabelText("기준 관측")).toBeTruthy();
  });

  it("keeps a foreign-area catalog pair opaque after an area switch", () => {
    const pair = {
      workAreaId: "area-1",
      a: { assetRef: `ksa-v1-${"a".repeat(64)}`, selector: selector("work-baseline", "a"), kind: "dsm",
        captureStartedAt: "2026-09-01T00:00:00Z", captureEndedAt: "2026-09-01T00:30:00Z", captureDate: null,
        revision: 1, declaredFileName: "a.tif", verticalIdentifier: null, verticalBasis: null, inspectionOutcome: "MEASURED" },
      b: { assetRef: `ksa-v1-${"b".repeat(64)}`, selector: selector("work-current", "b"), kind: "dsm",
        captureStartedAt: "2026-09-08T00:00:00Z", captureEndedAt: "2026-09-08T00:30:00Z", captureDate: null,
        revision: 1, declaredFileName: "b.tif", verticalIdentifier: null, verticalBasis: null, inspectionOutcome: "MEASURED" },
    };
    vi.stubGlobal("fetch", vi.fn());
    renderPanel({ canCreate: true, initialAnalysisId: null, initialSelectedDetail: null,
      initialPage: listPage([]), observations: [], siteObservations: [], initialWorkAreaId: "area-2",
      workAreas: [{ workAreaId: "area-1", name: "1구역" }, { workAreaId: "area-2", name: "2구역" }],
      catalogPair: pair,
      visualContext: { workAreaId: "area-1", visualAAssetRef: pair.a.assetRef, visualBAssetRef: pair.b.assetRef },
      visualReturnHref: "/sites/site-1?mode=compare&workAreaId=area-1" });
    // 구역이 바뀌면 다른 구역의 쌍은 검사하지 않는다.
    expect(screen.queryByText("가져온 쌍의 조건 확인")).toBeNull();
    expect(screen.getByText("이 구역의 분석 후보가 없습니다")).toBeTruthy();
  });
});

describe("first-use task order", () => {
  it("puts the pair form first and shelves the empty-history notice when candidates exist", () => {
    vi.stubGlobal("fetch", vi.fn());
    renderPanel({ canCreate: true, initialAnalysisId: null, initialSelectedDetail: null,
      initialPage: listPage([]), initialWorkAreaId: "area-1" });
    expect(screen.getByLabelText("기준 관측")).toBeTruthy();
    expect(screen.getByLabelText("현재 관측")).toBeTruthy();
    expect(screen.queryByText(/이 현장에는 아직 변화 분석 요청이 없습니다/)).toBeNull();
  });

  it("keeps the true-empty recovery copy when no candidates exist at all", () => {
    vi.stubGlobal("fetch", vi.fn());
    renderPanel({ canCreate: true, initialAnalysisId: null, initialSelectedDetail: null,
      initialPage: listPage([]), observations: [], siteObservations: [], initialWorkAreaId: "area-1" });
    expect(screen.getByText(/이 현장에는 아직 변화 분석 요청이 없습니다/)).toBeTruthy();
    expect(screen.getByText("이 구역의 분석 후보가 없습니다")).toBeTruthy();
    expect(screen.queryByLabelText("기준 관측")).toBeNull();
  });
});
