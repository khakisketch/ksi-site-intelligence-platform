/** @vitest-environment jsdom */
import { readFileSync } from "node:fs";
import { cleanup, render, screen } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
vi.mock("@/components/map/WorkAreaChoiceMap", () => ({ WorkAreaChoiceMap: () => <div>등록된 지도 경계</div> }));

import { AnalysisRequestPanel } from "@/app/sites/[siteId]/analysis/AnalysisRequestPanel";
import { MaskedAnalysisPanel } from "@/app/sites/[siteId]/analysis/MaskedAnalysisPanel";
import { SpatialTaskPanel } from "@/app/sites/[siteId]/spatial-tasks/[taskId]/SpatialTaskPanel";
import { SiteWorkspaceResults } from "@/app/sites/[siteId]/SiteWorkspaceResults";
import type { AnalysisView } from "@/lib/core-api/analysis";
import type { WorkspaceServerFacts } from "@/lib/site-workspace-entry";
import type { SpatialTaskOptions, SpatialTaskView } from "@/lib/spatial-task";

const selector = (workOrderId: string, digit: string) => ({
  workOrderId,
  submissionRef: `ers-v1-${digit.repeat(64)}`,
  revision: 1,
});
const observations = [
  { selector: selector("work-baseline", "a"), observationEpochId: "epoch-baseline", captureStartedAt: "2026-09-01T00:00:00Z", captureEndedAt: "2026-09-08T00:30:00Z", workAreaIds: ["area-1"] },
  { selector: selector("work-current", "b"), observationEpochId: "epoch-current", captureStartedAt: "2026-09-08T00:00:00Z", captureEndedAt: "2026-09-08T00:30:00Z", workAreaIds: ["area-1"] },
] as unknown as Parameters<typeof AnalysisRequestPanel>[0]["observations"];

function coverage() {
  return {
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
  };
}

function detailWith(uncertaintyM3: number | null, suitability: AnalysisView["suitabilityState"] = "PROVISIONAL_ACCURACY_UNVERIFIED"): AnalysisView {
  return {
    analysisId: "analysis-1",
    siteId: "site-1",
    workAreaId: "area-1",
    baseline: observations[0]!.selector,
    current: observations[1]!.selector,
    executionState: "COMPLETED",
    suitabilityState: suitability,
    blockers: [],
    result: {
      resultId: "result-core-1",
      reportDigest: `sha256:${"1".repeat(64)}`,
      numericResultIdentityDigest: `sha256:${"2".repeat(64)}`,
      computedAt: "2026-09-08T02:00:00Z",
      metrics: { cutM3: 12, fillM3: 20, netM3: 8, thresholdM: 0.1, uncertaintyM3 },
      coverage: coverage(),
      limitationCodes: [],
    },
    evidenceRevision: 1,
    evidenceDigest: `sha256:${"4".repeat(64)}`,
    evidenceHref: "/evidence",
    coverageHref: null,
    createdAt: "2026-09-08T01:00:00Z",
  } as unknown as AnalysisView;
}

function renderPanel(detail: AnalysisView | null, pageMetrics: { cutM3: number; fillM3: number; netM3: number; thresholdM: number; uncertaintyM3: number | null } | null) {
  vi.stubGlobal("fetch", vi.fn());
  const page = pageMetrics
    ? { siteId: "site-1", items: [{ analysisId: "analysis-1", siteId: "site-1", workAreaId: "area-1", executionState: "COMPLETED" as const, suitabilityState: detail?.suitabilityState ?? "PROVISIONAL_ACCURACY_UNVERIFIED" as const, createdAt: "2026-09-08T01:00:00Z", resultId: "result-core-1", metrics: pageMetrics, limitationCount: 0, analysisHref: "/x", newerSiblingAnalysisIds: [] }], nextCursor: null }
    : { siteId: "site-1", items: [], nextCursor: null };
  render(
    <AnalysisRequestPanel
      siteId="site-1"
      organizationId="org-1"
      principalId="operator-1"
      workAreas={[{ workAreaId: "area-1", name: "1구역" }]}
      observations={observations}
      siteObservations={observations}
      initialPage={page as never}
      initialSelectedDetail={detail as never}
      canCreate={false}
      initialAnalysisId={detail ? "analysis-1" : null}
    />,
  );
}

const facts = {
  siteId: "site-1",
  authorizedWorkAreaIds: ["area-1"],
  entryDefault: null,
  observations: [
    { observationEpochId: "epoch-base", workAreaId: "area-1", workOrderId: "w1", assetRef: "a-base", submissionRef: "s1", revision: 1, kind: "dsm", displayReady: true, inspectedRasterAvailable: true, chronologyCandidate: true, captureSourcesAgree: true, viewAvailable: true, viewUnavailableReason: null, viewAssetRef: "a-base", newerRevisionPending: false, newerRevisionState: null, captureStartedAt: "2026-10-25T03:00:00Z", captureEndedAt: "2026-10-25T03:30:00Z", captureDate: null },
    { observationEpochId: "epoch-cur", workAreaId: "area-1", workOrderId: "w2", assetRef: "a-cur", submissionRef: "s2", revision: 1, kind: "dsm", displayReady: true, inspectedRasterAvailable: true, chronologyCandidate: true, captureSourcesAgree: true, viewAvailable: true, viewUnavailableReason: null, viewAssetRef: "a-cur", newerRevisionPending: false, newerRevisionState: null, captureStartedAt: "2026-10-26T03:00:00Z", captureEndedAt: "2026-10-26T03:30:00Z", captureDate: null },
  ],
  analyses: [],
} as unknown as WorkspaceServerFacts;

function workspaceDetail(uncertaintyM3: number | null, suitability: AnalysisView["suitabilityState"] = "PROVISIONAL_ACCURACY_UNVERIFIED"): AnalysisView {
  return {
    analysisId: "analysis-9",
    siteId: "site-1",
    workAreaId: "area-1",
    baseline: { workOrderId: "w1", submissionRef: "s1", revision: 1 },
    current: { workOrderId: "w2", submissionRef: "s2", revision: 1 },
    executionState: "COMPLETED",
    suitabilityState: suitability,
    blockers: [],
    result: {
      resultId: "res-9",
      reportDigest: "rd",
      numericResultIdentityDigest: "nd",
      computedAt: "2026-10-25T10:25:00Z",
      metrics: { cutM3: 0.02, fillM3: 0.02, netM3: 0, thresholdM: 0.1, uncertaintyM3 },
      coverage: { coverageWitnessDigest: "cw", rows: 1, columns: 1, selectedCellCount: 1, commonValidCellCount: 1, unavailableCellCount: 0, thresholdExcludedCellCount: 0, cellAreaM2: 1, selectedAreaM2: 1, commonValidAreaM2: 1, bounds: [0, 0, 1, 1] },
      limitationCodes: [],
    },
    evidenceRevision: 1,
    evidenceDigest: "ed",
    evidenceHref: "/evidence",
    coverageHref: null,
    createdAt: "2026-10-25T10:25:00Z",
  } as unknown as AnalysisView;
}

function renderWorkspaceExplicit(detail: AnalysisView | null) {
  const explicit = detail ? { status: "ready", basis: "explicit", analysis: { analysisId: detail.analysisId, workAreaId: detail.workAreaId, baseline: detail.baseline, current: detail.current } } as never : null;
  return renderToStaticMarkup(
    <SiteWorkspaceResults
      sitePath="/sites/site-1"
      areaLabel="1구역"
      areaAnalyses={[]}
      analysesKnown
      explicitResult={explicit}
      explicitDetail={detail}
      leadDetail={null}
      facts={facts}
      canCreateAnalysis={false}
      scopedCompareHref="/sites/site-1/analysis?workAreaId=area-1"
      visualContext={null}
    />,
  );
}

function renderWorkspaceList(metrics: { cutM3: number; fillM3: number; netM3: number; thresholdM: number; uncertaintyM3: number | null } | null, suitability: AnalysisView["suitabilityState"] = "PROVISIONAL_ACCURACY_UNVERIFIED") {
  const items = metrics ? [{ analysisId: "a1", siteId: "site-1", workAreaId: "area-1", executionState: "COMPLETED" as const, suitabilityState: suitability, createdAt: "2026-10-25T10:25:00Z", resultId: "res-1", metrics, limitationCount: 0, analysisHref: "/x" }] : [];
  return renderToStaticMarkup(
    <SiteWorkspaceResults
      sitePath="/sites/site-1"
      areaLabel="1구역"
      areaAnalyses={items as never}
      analysesKnown
      explicitResult={null}
      explicitDetail={null}
      leadDetail={null}
      facts={facts}
      canCreateAnalysis={false}
      scopedCompareHref="/sites/site-1/analysis?workAreaId=area-1"
      visualContext={null}
    />,
  );
}

const taskId = `st-${"a".repeat(32)}`;
const taskBase: SpatialTaskView = {
  task: { taskId, siteId: "site-a", revision: 1,
    selection: { purpose: "OBSERVED_CHANGE", workAreaId: null, inputs: null },
    analysisId: null, executionRequested: false, createdAt: "2026-10-27T00:00:00Z", expiresAt: "2026-11-03T00:00:00Z" },
  state: "AREA_REQUIRED", selectionHref: `/sites/site-a/spatial-tasks/${taskId}`, analysisHref: null,
  readiness: null, analysis: null,
} as unknown as SpatialTaskView;
const taskOptions: SpatialTaskOptions = {
  siteId: "site-a", areas: [{ workAreaId: "area-a", name: "동측 구역" }], nextOffset: null,
  observations: ["a", "b"].map((letter, index) => ({
    selector: { workOrderId: `order-${letter}`, submissionRef: `ers-v1-${letter.repeat(64)}`, revision: 1 },
    observationEpochId: `epoch-${letter}`, captureStartedAt: `2026-10-${20 + index}T00:00:00Z`,
    captureEndedAt: `2026-10-${20 + index}T01:00:00Z`, workAreaIds: ["area-a"],
  })),
} as unknown as SpatialTaskOptions;

function taskCompletedView(uncertaintyM3: number | null): SpatialTaskView {
  const inputs = { baseline: taskOptions.observations[0]!.selector, current: taskOptions.observations[1]!.selector };
  return { ...taskBase, state: "ANALYSIS_LINKED", task: { ...taskBase.task,
    selection: { purpose: "OBSERVED_CHANGE", workAreaId: "area-a", inputs },
    executionRequested: true, analysisId: "analysis-a" },
    analysis: { analysisId: "analysis-a", siteId: "site-a", workAreaId: "area-a", ...inputs,
      executionState: "COMPLETED", suitabilityState: "PROVISIONAL_ACCURACY_UNVERIFIED", blockers: [],
      evidenceRevision: 1, evidenceDigest: `sha256:${"a".repeat(64)}`, evidenceHref: "/v2/evidence",
      coverageHref: "/v2/coverage", createdAt: taskBase.task.createdAt,
      result: { resultId: "result-a", reportDigest: `sha256:${"a".repeat(64)}`,
        numericResultIdentityDigest: `sha256:${"b".repeat(64)}`, computedAt: taskBase.task.createdAt,
        metrics: { cutM3: 5, fillM3: 7, netM3: 2, thresholdM: 0, uncertaintyM3 },
        coverage: { coverageWitnessDigest: `sha256:${"c".repeat(64)}`, rows: 2, columns: 2,
          selectedCellCount: 4, commonValidCellCount: 4, unavailableCellCount: 0,
          thresholdExcludedCellCount: 0, cellAreaM2: 1, selectedAreaM2: 4, commonValidAreaM2: 4,
          bounds: [0, 0, 2, 2] }, limitationCodes: ["ACCURACY_UNVERIFIED"] },
    } } as unknown as SpatialTaskView;
}

const maskedFixture = JSON.parse(readFileSync("test/masked-wire-fixture.json", "utf-8")) as Record<string, unknown>;
const maskedDigest = maskedFixture.sourceCalculationIdentityDigest as string;
const maskedBaseProps = {
  siteId: "site-1",
  workAreaId: "area-1",
  workAreaName: "구역 A",
  canRequest: true,
  maskBudgetBytes: 1024 * 1024,
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("recorded volume uncertainty visibility", () => {
  // Numeric values are UI fixtures only: the current V2/V3 wire contracts
  // record null, not a computed volume-uncertainty estimate.
  it("analysis detail shows recorded unknown without asserting nonzero", () => {
    renderPanel(detailWith(null), null);
    const region = screen.getByRole("region", { name: /^계산 결과/ });
    expect(region.textContent).toMatch(/불확실성 미기록/);
    expect(region.textContent).toMatch(/기록된 값이 없으므로 0으로 볼 수 없습니다/);
    expect(region.textContent).toMatch(/검사점 평가와 별개입니다/);
    expect(region.textContent).not.toMatch(/0이 아니며/);
    expect(region.textContent).not.toMatch(/Core 기록값 없음/);
  });

  it("analysis detail shows recorded numeric uncertainty when present", () => {
    renderPanel(detailWith(1.5), null);
    const region = screen.getByRole("region", { name: /^계산 결과/ });
    expect(region.textContent).toMatch(/불확실성 ±1\.5 m³/);
    expect(region.textContent).toMatch(/\(기록값\)/);
  });

  it("analysis detail treats 0 as recorded numeric, not unknown", () => {
    renderPanel(detailWith(0), null);
    const region = screen.getByRole("region", { name: /^계산 결과/ });
    expect(region.textContent).toMatch(/불확실성/);
    expect(region.textContent).toMatch(/±0/);
    expect(region.textContent).not.toMatch(/미기록/);
  });

  it("analysis detail keeps EVALUATED distinct from known uncertainty", () => {
    renderPanel(detailWith(null, "EVALUATED"), null);
    const region = screen.getByRole("region", { name: /^계산 결과/ });
    expect(region.textContent).toMatch(/불확실성 미기록/);
    expect(region.textContent).toMatch(/기록된 값이 없으므로 0으로 볼 수 없습니다/);
    expect(region.textContent).toMatch(/독립 평가 근거가 있습니다/);
  });

  it("analysis result-list fallback shows recorded unknown when only summary metrics exist", () => {
    vi.stubGlobal("fetch", vi.fn());
    const secondMetrics = { cutM3: 12, fillM3: 20, netM3: 8, thresholdM: 0.1, uncertaintyM3: null };
    const page = {
      siteId: "site-1",
      items: [
        { analysisId: "analysis-1", siteId: "site-1", workAreaId: "area-1", executionState: "COMPLETED" as const, suitabilityState: "PROVISIONAL_ACCURACY_UNVERIFIED" as const, createdAt: "2026-09-08T01:00:00Z", resultId: "result-core-1", metrics: detailWith(null).result!.metrics, limitationCount: 0, analysisHref: "/x", newerSiblingAnalysisIds: [] },
        { analysisId: "analysis-2", siteId: "site-1", workAreaId: "area-1", executionState: "COMPLETED" as const, suitabilityState: "PROVISIONAL_ACCURACY_UNVERIFIED" as const, createdAt: "2026-09-08T02:00:00Z", resultId: "result-core-2", metrics: secondMetrics, limitationCount: 0, analysisHref: "/y", newerSiblingAnalysisIds: [] },
      ],
      nextCursor: null,
    };
    render(
      <AnalysisRequestPanel
        siteId="site-1"
        organizationId="org-1"
        principalId="operator-1"
        workAreas={[{ workAreaId: "area-1", name: "1구역" }]}
        observations={observations}
        siteObservations={observations}
        initialPage={page as never}
        initialSelectedDetail={detailWith(null) as never}
        canCreate={false}
        initialAnalysisId="analysis-1"
      />,
    );
    const regions = screen.getAllByRole("region", { name: /^계산 결과/ });
    expect(regions).toHaveLength(2);
    expect(regions[1]!.textContent).toMatch(/불확실성 미기록/);
    expect(regions[1]!.textContent).toMatch(/기록된 값이 없으므로 0으로 볼 수 없습니다/);
  });

  it("analysis shows no uncertainty line when no metrics exist", () => {
    renderPanel(null, null);
    expect(screen.queryByRole("region", { name: /^계산 결과/ })).toBeNull();
    expect(document.body.textContent ?? "").not.toMatch(/불확실성 미기록/);
    expect(document.body.textContent ?? "").not.toMatch(/불확실성 ±/);
  });

  it("workspace explicit path shows recorded unknown without asserting nonzero", () => {
    const html = renderWorkspaceExplicit(workspaceDetail(null));
    expect(html).toMatch(/불확실성 미기록/);
    expect(html).toMatch(/기록된 값이 없으므로 0으로 볼 수 없습니다/);
    expect(html).not.toMatch(/0이 아니며/);
  });

  it("workspace explicit path treats 0 as numeric", () => {
    const html = renderWorkspaceExplicit(workspaceDetail(0));
    expect(html).toMatch(/불확실성/);
    expect(html).toMatch(/±0/);
    expect(html).not.toMatch(/미기록/);
  });

  it("workspace result-list path shows recorded unknown", () => {
    const html = renderWorkspaceList({ cutM3: 0.02, fillM3: 0.02, netM3: 0, thresholdM: 0.1, uncertaintyM3: null });
    expect(html).toMatch(/불확실성 미기록/);
    expect(html).toMatch(/기록된 값이 없으므로 0으로 볼 수 없습니다/);
  });

  it("workspace result-list path shows recorded numeric including EVALUATED", () => {
    const html = renderWorkspaceList({ cutM3: 0.02, fillM3: 0.02, netM3: 0, thresholdM: 0.1, uncertaintyM3: 2.5 }, "EVALUATED");
    expect(html).toMatch(/불확실성 ±2\.5 m³/);
    expect(html).toMatch(/\(기록값\)/);
    expect(html).toMatch(/분석 조건 확인 결과가 있습니다/);
  });

  it("workspace shows no uncertainty line when record has no result", () => {
    const noResult = { ...workspaceDetail(null), result: null, executionState: "COMPLETED" as const, suitabilityState: "BLOCKED" as const, blockers: [{ code: "X", epoch: null, evidenceRef: null, detail: null }] };
    const html = renderWorkspaceExplicit(noResult as unknown as AnalysisView);
    expect(html).not.toMatch(/불확실성 미기록/);
    expect(html).not.toMatch(/불확실성 ±/);
  });

  it("spatial task direct result shows recorded unknown without asserting nonzero", () => {
    render(<SpatialTaskPanel initialView={taskCompletedView(null)} initialOptions={taskOptions} siteName="테스트 현장" areas={[]} canWrite />);
    expect(screen.getByText(/불확실성 미기록/)).toBeTruthy();
    expect(screen.getByText(/기록된 값이 없으므로 0으로 볼 수 없습니다/)).toBeTruthy();
    expect(document.body.textContent ?? "").not.toMatch(/0이 아니며/);
    expect(screen.getByText("5 m³")).toBeTruthy();
  });

  it("spatial task direct result treats 0 as numeric, not unknown", () => {
    render(<SpatialTaskPanel initialView={taskCompletedView(0)} initialOptions={taskOptions} siteName="테스트 현장" areas={[]} canWrite />);
    expect(screen.getByText(/불확실성 ±0/)).toBeTruthy();
    expect(screen.queryByText(/불확실성 미기록/)).toBeNull();
  });

  it("spatial task direct result shows recorded numeric when present", () => {
    render(<SpatialTaskPanel initialView={taskCompletedView(2.5)} initialOptions={taskOptions} siteName="테스트 현장" areas={[]} canWrite />);
    expect(screen.getByText(/불확실성 ±2\.5/)).toBeTruthy();
  });

  it("spatial task shows no uncertainty line when result is absent", () => {
    const failed = taskCompletedView(null);
    failed.analysis = { ...failed.analysis!, executionState: "FAILED" as const, result: null };
    render(<SpatialTaskPanel initialView={failed} initialOptions={taskOptions} siteName="테스트 현장" areas={[]} canWrite />);
    expect(screen.queryByText(/불확실성 미기록/)).toBeNull();
    expect(screen.queryByText(/불확실성 ±/)).toBeNull();
    expect(screen.queryByText(/m³/)).toBeNull();
  });

  it("masked V3 report shows recorded unknown without implying numeric support", () => {
    render(
      <MaskedAnalysisPanel
        {...maskedBaseProps}
        sourceCalculationIdentityDigest={maskedDigest}
        initialChild={maskedFixture.childViewReady as never}
        initialCalculation={maskedFixture.detailViewAvailable as never}
      />,
    );
    expect(screen.getByText(/독립 마스크 계산 결과/)).toBeTruthy();
    expect(screen.getByText(/불확실성 미기록/)).toBeTruthy();
    expect(screen.getByText(/기록된 값이 없으므로 0으로 볼 수 없습니다/)).toBeTruthy();
    expect(document.body.textContent ?? "").not.toMatch(/불확실성 ±/);
  });

  it("masked V3 shows no uncertainty line when no report exists", () => {
    render(
      <MaskedAnalysisPanel
        {...maskedBaseProps}
        sourceCalculationIdentityDigest={maskedDigest}
        initialChild={maskedFixture.childViewReady as never}
        initialCalculation={maskedFixture.detailViewPending as never}
      />,
    );
    expect(screen.queryByText(/독립 마스크 계산 결과/)).toBeNull();
    expect(screen.queryByText(/불확실성 미기록/)).toBeNull();
    expect(screen.queryByText(/불확실성 ±/)).toBeNull();
  });
});
