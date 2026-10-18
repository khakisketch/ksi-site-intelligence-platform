/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const router = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

import { AnalysisRequestPanel } from "@/app/sites/[siteId]/analysis/AnalysisRequestPanel";
import type { AnalysisListPage, AnalysisObservationOption, AnalysisView } from "@/lib/core-api/analysis";

const selector = (workOrderId: string, digit: string) => ({ workOrderId, submissionRef: `ers-v1-${digit.repeat(64)}`, revision: 1 });

type Scoped = AnalysisObservationOption & { workAreaIds: string[] };

function option(workOrderId: string, digit: string, epoch: string, start: string, end: string, workAreaIds = ["area-1"]): Scoped {
  return { selector: selector(workOrderId, digit), observationEpochId: epoch, captureStartedAt: start, captureEndedAt: end, workAreaIds };
}

const threeEpochs: Scoped[] = [
  option("work-a", "a", "epoch-a", "2026-09-01T00:00:00Z", "2026-09-01T00:30:00Z"),
  option("work-b", "b", "epoch-b", "2026-09-08T00:00:00Z", "2026-09-08T00:30:00Z"),
  option("work-c", "c", "epoch-c", "2026-09-15T00:00:00Z", "2026-09-15T00:30:00Z"),
];

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json" } });
}

function emptyPage(): AnalysisListPage {
  return { siteId: "site-1", items: [], nextCursor: null };
}

function renderPairPanel(overrides: Partial<Parameters<typeof AnalysisRequestPanel>[0]> = {}) {
  const delegateFetch = globalThis.fetch;
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    if (/\/reviews(?:\?|$)/.test(url) && init?.method !== "POST") {
      return Promise.resolve(json({ target: null, items: [], nextCursor: null }));
    }
    return delegateFetch(input, init);
  });
  vi.stubGlobal("fetch", fetchMock);
  const view = render(<AnalysisRequestPanel
    siteId="site-1"
    organizationId="org-1"
    principalId="operator-1"
    workAreas={[{ workAreaId: "area-1", name: "1구역" }]}
    observations={threeEpochs}
    initialPage={emptyPage()}
    initialSelectedDetail={null}
    canCreate
    initialAnalysisId={null}
    {...overrides}
  />);
  return { ...view, fetchMock };
}

function submitButton() {
  return screen.getByRole("button", { name: "변화 분석 요청" }) as HTMLButtonElement;
}

afterEach(() => {
  cleanup();
  router.replace.mockReset();
  vi.restoreAllMocks();
  sessionStorage.clear();
  vi.unstubAllGlobals();
});

describe("analysis pair feedback", () => {
  it("auto-suggests the latest prior baseline only while none is chosen", () => {
    renderPairPanel();
    fireEvent.change(screen.getByLabelText("작업구역"), { target: { value: "area-1" } });
    fireEvent.change(screen.getByLabelText("현재 관측"), { target: { value: "2" } });
    expect((screen.getByLabelText("기준 관측") as HTMLSelectElement).value).toBe("1");
    expect(submitButton().disabled).toBe(false);
  });

  it("preserves an explicitly chosen baseline when current changes, gating reversed chronology", () => {
    renderPairPanel();
    fireEvent.change(screen.getByLabelText("작업구역"), { target: { value: "area-1" } });
    fireEvent.change(screen.getByLabelText("기준 관측"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("현재 관측"), { target: { value: "1" } });

    expect((screen.getByLabelText("기준 관측") as HTMLSelectElement).value).toBe("2");
    expect(screen.getByRole("status").textContent).toContain("시간 역전");
    expect(submitButton().disabled).toBe(true);

    fireEvent.change(screen.getByLabelText("현재 관측"), { target: { value: "0" } });
    expect((screen.getByLabelText("기준 관측") as HTMLSelectElement).value).toBe("2");
    expect(submitButton().disabled).toBe(true);
  });

  it("blocks a programmatic form submit of a known-bad pair before any POST", async () => {
    const { fetchMock } = renderPairPanel();
    fireEvent.change(screen.getByLabelText("작업구역"), { target: { value: "area-1" } });
    fireEvent.change(screen.getByLabelText("기준 관측"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("현재 관측"), { target: { value: "1" } });
    expect(submitButton().disabled).toBe(true);

    // Disabled 버튼을 우회하는 Enter·프로그래밍 제출도 POST 없이 차단된다.
    fireEvent.submit(document.querySelector("#new-analysis-request form")!);
    expect(fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === "POST")).toHaveLength(0);
    // submit() 가드 경로가 alert 오류를 남긴다 — 미리 표시된 status 안내와 별개다.
    expect(screen.getByRole("alert").textContent).toContain("시간 역전");
    expect(sessionStorage.length).toBe(0);
  });

  it("gates the same observation in both pickers with a precise reason", () => {
    renderPairPanel();
    fireEvent.change(screen.getByLabelText("작업구역"), { target: { value: "area-1" } });
    fireEvent.change(screen.getByLabelText("기준 관측"), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText("현재 관측"), { target: { value: "0" } });

    expect(screen.getByRole("status").textContent).toContain("같은 관측");
    expect(submitButton().disabled).toBe(true);
  });

  it("gates overlapping intervals and unparsable capture windows", () => {
    const overlapping: Scoped[] = [
      option("work-a", "a", "epoch-a", "2026-09-01T00:00:00Z", "2026-09-01T01:00:00Z"),
      option("work-b", "b", "epoch-b", "2026-09-01T00:30:00Z", "2026-09-01T01:30:00Z"),
    ];
    renderPairPanel({ observations: overlapping });
    fireEvent.change(screen.getByLabelText("작업구역"), { target: { value: "area-1" } });
    fireEvent.change(screen.getByLabelText("기준 관측"), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText("현재 관측"), { target: { value: "1" } });
    expect(screen.getByRole("status").textContent).toContain("겹칩니다");
    expect(submitButton().disabled).toBe(true);

    cleanup();
    const invalid: Scoped[] = [
      option("work-a", "a", "epoch-a", "not-a-time", "2026-09-01T00:30:00Z"),
      option("work-b", "b", "epoch-b", "2026-09-08T00:00:00Z", "2026-09-08T00:30:00Z"),
    ];
    renderPairPanel({ observations: invalid });
    fireEvent.change(screen.getByLabelText("작업구역"), { target: { value: "area-1" } });
    fireEvent.change(screen.getByLabelText("기준 관측"), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText("현재 관측"), { target: { value: "1" } });
    expect(screen.getByRole("status").textContent).toContain("촬영 구간을 확인하지 못했습니다");
    expect(submitButton().disabled).toBe(true);
  });

  it("clears both pickers with an announcement when the work area changes", () => {
    const twoAreas: Scoped[] = [
      { ...threeEpochs[0]!, workAreaIds: ["area-1"] },
      { ...threeEpochs[1]!, workAreaIds: ["area-1"] },
      { ...threeEpochs[2]!, workAreaIds: ["area-2"] },
    ];
    renderPairPanel({
      observations: twoAreas,
      workAreas: [{ workAreaId: "area-1", name: "1구역" }, { workAreaId: "area-2", name: "2구역" }],
    });
    fireEvent.change(screen.getByLabelText("작업구역"), { target: { value: "area-1" } });
    fireEvent.change(screen.getByLabelText("기준 관측"), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText("현재 관측"), { target: { value: "1" } });
    expect(submitButton().disabled).toBe(false);

    fireEvent.change(screen.getByLabelText("작업구역"), { target: { value: "area-2" } });
    expect((screen.getByLabelText("기준 관측") as HTMLSelectElement).value).toBe("");
    expect((screen.getByLabelText("현재 관측") as HTMLSelectElement).value).toBe("");
    expect(screen.getByText(/기준·현재 선택을 모두 지웠습니다/)).toBeTruthy();
    expect(screen.getAllByRole("status")).toHaveLength(1);
  });

  it("keeps full work names in native options and a two-column selector layout from 1024px", () => {
    const longName = "한강 하류 3공구 성토부 주간 비교 관측 작업 이름이 매우 긴 경우";
    renderPairPanel({ workOrderNames: { "work-a": longName } });
    const form = document.querySelector("form")!;
    expect(form.className).toContain("lg:grid-cols-2");
    expect(form.querySelector("select")?.closest("label")?.className).toContain("lg:col-span-2");

    fireEvent.change(screen.getByLabelText("작업구역"), { target: { value: "area-1" } });
    const baseline = screen.getByLabelText("기준 관측") as HTMLSelectElement;
    expect(baseline.options[1]?.textContent).toContain(longName);
    expect(baseline.options[1]?.textContent).toContain("2026. 9. 1.");
    expect(baseline.options[1]?.textContent).not.toContain("등록 버전");
  });

  it("summarizes the latest result and next action before the request form", () => {
    const completed: AnalysisView = {
      analysisId: "analysis-1",
      siteId: "site-1",
      workAreaId: "area-1",
      baseline: threeEpochs[0]!.selector,
      current: threeEpochs[1]!.selector,
      executionState: "COMPLETED",
      suitabilityState: "EVALUATED",
      blockers: [],
      result: null,
      evidenceRevision: 1,
      evidenceDigest: "sha256:digest",
      evidenceHref: "/evidence",
      coverageHref: "/coverage",
      createdAt: "2026-09-08T01:00:00Z",
    };
    renderPairPanel({
      initialPage: {
        siteId: "site-1",
        items: [{
          analysisId: "analysis-1",
          siteId: "site-1",
          workAreaId: "area-1",
          executionState: "COMPLETED",
          suitabilityState: "EVALUATED",
          createdAt: "2026-09-08T01:00:00Z",
          resultId: null,
          metrics: null,
          limitationCount: 0,
          analysisHref: "/v2/sites/site-1/analyses/analysis-1",
        }],
        nextCursor: null,
      },
      initialSelectedDetail: completed,
      initialAnalysisId: "analysis-1",
    });
    const summary = screen.getByLabelText("최근 변화 분석 요약");
    const request = screen.getByText("새 변화 분석 요청");
    expect(summary.textContent).toContain("최근 실행 상태: 실행 완료. 적합성 상태: 평가 근거 있음.");
    expect(summary.textContent).toContain("정확도 보증이 아닙니다");
    expect(summary.compareDocumentPosition(request) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const history = screen.getByRole("region", { name: "변화 분석 이력" });
    expect(history.compareDocumentPosition(request) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("link", { name: "변화 분석 이력으로 이동" }).getAttribute("href")).toBe("#analysis-history");
  });
});
