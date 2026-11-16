import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  CoverageStrip,
  ResultTrend,
  UncertaintyChip,
  VolumeBalance,
  type TrendPoint,
} from "@/app/sites/[siteId]/AnalysisResultVisuals";
import { SiteWorkspaceResults, type ResultReviewSummary } from "@/app/sites/[siteId]/SiteWorkspaceResults";
import type { AnalysisMetrics, AnalysisView } from "@/lib/core-api/analysis";
import type { WorkspaceServerFacts } from "@/lib/site-workspace-entry";

const metrics = (cut: number, fill: number, uncertainty: number | null = null): AnalysisMetrics => ({
  cutM3: cut,
  fillM3: fill,
  netM3: fill - cut,
  thresholdM: 0,
  uncertaintyM3: uncertainty,
});

describe("VolumeBalance", () => {
  it("labels the net change as a calculated difference and writes no direction sentence", () => {
    for (const pair of [[10, 25], [25, 10], [5, 5]] as const) {
      const html = renderToStaticMarkup(<VolumeBalance metrics={metrics(pair[0], pair[1])} />);
      expect(html).toContain("계산상 순변화");
      expect(html).not.toContain("더 많습니다");
      expect(html).not.toContain("같습니다");
    }
  });

  it("signs a positive net change and keeps cut and fill as positive magnitudes", () => {
    const html = renderToStaticMarkup(<VolumeBalance metrics={metrics(10, 25)} />);
    expect(html).toContain("+15");
    expect(html).toContain("10 m³");
    expect(html).toContain("25 m³");
  });

  it("scales the bars against the larger side and never invents a length for zero", () => {
    const html = renderToStaticMarkup(<VolumeBalance metrics={metrics(5, 20)} />);
    expect(html).toContain("width:25%");
    expect(html).toContain("width:100%");
    const empty = renderToStaticMarkup(<VolumeBalance metrics={metrics(0, 0)} />);
    expect(empty).toContain("width:0%");
    expect(empty).not.toContain("NaN");
  });

  it("describes the bar for assistive technology with both values", () => {
    const html = renderToStaticMarkup(<VolumeBalance metrics={metrics(3, 4)} />);
    expect(html).toContain('aria-label="깎임 3 m³, 쌓임 4 m³"');
  });
});

describe("VolumeBalance equal weight", () => {
  it("puts cut and fill before the net change and gives them the larger type", () => {
    const html = renderToStaticMarkup(<VolumeBalance metrics={metrics(1000, 1000)} />);
    expect(html.indexOf("깎임")).toBeLessThan(html.indexOf("순변화"));
    expect(html.indexOf("쌓임")).toBeLessThan(html.indexOf("순변화"));
    // 두 값이 같은 크기의 글자 등급이고, 순변화는 더 작은 등급이다.
    expect(html.match(/text-hero/g)?.length).toBe(2);
    expect(html).toContain("1,000");
    expect(html).not.toContain("+0");
  });

  it("does not turn an offsetting pair into no change", () => {
    const html = renderToStaticMarkup(<VolumeBalance metrics={metrics(1000, 1000)} />);
    expect(html).not.toContain("변화 없음");
    expect(html).not.toContain("변화가 없");
    expect(html).toContain("계산상 순변화");
  });
});

describe("UncertaintyChip", () => {
  it("says recorded-unknown instead of zero, and zero stays a recorded value", () => {
    expect(renderToStaticMarkup(<UncertaintyChip uncertaintyM3={null} />)).toContain("불확실성 미기록");
    const zero = renderToStaticMarkup(<UncertaintyChip uncertaintyM3={0} />);
    expect(zero).toContain("불확실성 ±0 m³ (기록값)");
    expect(zero).not.toContain("미기록");
  });

  it("renders nothing for a non-finite value rather than a guessed text", () => {
    expect(renderToStaticMarkup(<UncertaintyChip uncertaintyM3={Number.NaN} />)).toBe("");
  });
});

const point = (id: string, sortKey: string, label: string, cut: number, fill: number): TrendPoint => ({
  analysisId: id,
  sortKey,
  label,
  metrics: metrics(cut, fill),
});

describe("ResultTrend", () => {
  it("does not draw a chart with fewer than two comparable results", () => {
    const html = renderToStaticMarkup(
      <ResultTrend points={[point("a", "2026-11-01", "11.1", 1, 2)]} currentId="a" />,
    );
    expect(html).toContain("비교할 수 있는 이전 결과가 없습니다");
    expect(html).not.toContain("<svg");
  });

  it("orders by observation date, keeps the latest six, and marks the current one", () => {
    const points = [7, 3, 1, 5, 2, 6, 4].map((day) => point(`a${day}`, `2026-11-0${day}`, `11.${day}`, day, day * 2));
    const html = renderToStaticMarkup(<ResultTrend points={points} currentId="a7" />);
    const labels = [...html.matchAll(/text-micro[^>]*>(\d+\.\d+)</g)].map((match) => match[1]);
    expect(labels).toEqual(["11.2", "11.3", "11.4", "11.5", "11.6", "11.7"]);
    expect(html).toContain("font-bold text-ink-1");
  });

  it("uses one scale for every bar, prints its end value, and exposes the values as a table", () => {
    const html = renderToStaticMarkup(
      <ResultTrend
        points={[point("a", "2026-11-01", "11.1", 10, 20), point("b", "2026-11-02", "11.2", 5, 40)]}
        currentId="b"
        conditions="같은 영역 · 임계값 0.1 m · 셀 1 m"
      />,
    );
    expect(html).toContain("<table");
    expect(html).toContain("깎임 10 m³ · 쌓임 20 m³");
    expect(html).toContain("깎임 5 m³ · 쌓임 40 m³");
    expect(html).toContain("40 m³");
    // 비교 조건은 접힌 상세에 있고, 범례만 앞에 둔다.
    expect(html).toContain("비교 조건");
    expect(html).toContain("현재 관측일 기준 · 같은 영역 · 임계값 0.1 m · 셀 1 m");
  });
});

describe("CoverageStrip", () => {
  const coverage = {
    coverageWitnessDigest: "w",
    rows: 4,
    columns: 5,
    selectedCellCount: 20,
    commonValidCellCount: 15,
    unavailableCellCount: 2,
    thresholdExcludedCellCount: 3,
    cellAreaM2: 0.01,
    selectedAreaM2: 0.2,
    commonValidAreaM2: 0.15,
    bounds: [0, 0, 1, 1] as [number, number, number, number],
  };

  it("shows how many selected cells were used and counts excluded cells without drawing a map", () => {
    const html = renderToStaticMarkup(<CoverageStrip coverage={coverage} />);
    expect(html).toContain("15 / 20");
    expect(html).toContain("width:75%");
    expect(html).toContain(">5<");
    expect(html).not.toContain("<canvas");
  });
});

const baseObservation = (id: string, sub: string, order: number, day: number) => ({
  observationEpochId: id,
  workAreaId: "area-1",
  workOrderId: `w${order}`,
  assetRef: `a-${id}`,
  submissionRef: sub,
  revision: 1,
  kind: "dsm",
  displayReady: true,
  inspectedRasterAvailable: true,
  chronologyCandidate: true,
  captureSourcesAgree: true,
  viewAvailable: true,
  viewUnavailableReason: null,
  viewAssetRef: `a-${id}`,
  newerRevisionPending: false,
  newerRevisionState: null,
  captureStartedAt: `2026-11-0${day}T03:00:00Z`,
  captureEndedAt: `2026-11-0${day}T03:30:00Z`,
  captureDate: null,
});

const trendFacts = {
  siteId: "site-1",
  authorizedWorkAreaIds: ["area-1"],
  entryDefault: null,
  observations: [
    baseObservation("e1", "s1", 1, 1),
    baseObservation("e2", "s2", 2, 2),
    baseObservation("e3", "s3", 3, 3),
    baseObservation("e4", "s4", 4, 4),
  ],
  analyses: [],
} as unknown as WorkspaceServerFacts;

const view = (
  id: string,
  from: string,
  to: string,
  cut: number,
  fill: number,
  options: { threshold?: number; cell?: number; createdAt?: string; workAreaId?: string } = {},
): AnalysisView => ({
  analysisId: id,
  siteId: "site-1",
  workAreaId: options.workAreaId ?? "area-1",
  baseline: { workOrderId: `w${from.slice(1)}`, submissionRef: from, revision: 1 },
  current: { workOrderId: `w${to.slice(1)}`, submissionRef: to, revision: 1 },
  executionState: "COMPLETED",
  suitabilityState: "PROVISIONAL_ACCURACY_UNVERIFIED",
  blockers: [],
  result: {
    resultId: `res-${id}`,
    reportDigest: "rd",
    numericResultIdentityDigest: "nd",
    computedAt: "2026-11-09T01:00:00Z",
    metrics: { cutM3: cut, fillM3: fill, netM3: fill - cut, thresholdM: options.threshold ?? 0.1, uncertaintyM3: null },
    coverage: {
      coverageWitnessDigest: "cw", rows: 1, columns: 1, selectedCellCount: 1, commonValidCellCount: 1,
      unavailableCellCount: 0, thresholdExcludedCellCount: 0, cellAreaM2: options.cell ?? 1,
      selectedAreaM2: 1, commonValidAreaM2: 1, bounds: [0, 0, 1, 1],
    },
    limitationCodes: [],
  },
  evidenceRevision: 1,
  evidenceDigest: "ed",
  evidenceHref: "/evidence",
  coverageHref: null,
  createdAt: options.createdAt ?? "2026-11-09T01:00:00Z",
} as unknown as AnalysisView);

function renderTrend(focal: AnalysisView, peers: AnalysisView[], extra: { review?: ResultReviewSummary | null } = {}) {
  return renderToStaticMarkup(
    <SiteWorkspaceResults
      sitePath="/sites/site-1"
      areaLabel="1영역"
      areaAnalyses={[]}
      analysesKnown
      explicitResult={{ status: "ready", basis: "explicit", analysis: { analysisId: focal.analysisId, workAreaId: focal.workAreaId, baseline: focal.baseline, current: focal.current } } as never}
      explicitDetail={focal}
      leadDetail={null}
      facts={trendFacts}
      canCreateAnalysis={false}
      scopedCompareHref="/sites/site-1/analysis?workAreaId=area-1"
      visualContext={null}
      peerDetails={peers}
      reviewSummary={extra.review ?? null}
    />,
  );
}

describe("SiteWorkspaceResults comparable trend", () => {
  it("compares only results of the same area, threshold and cell size, by observation date", () => {
    const html = renderTrend(view("now", "s2", "s3", 3, 9), [
      view("old", "s1", "s2", 4, 1),
      view("other-threshold", "s1", "s3", 50, 50, { threshold: 0.5 }),
      view("other-cell", "s1", "s4", 60, 60, { cell: 4 }),
      view("other-area", "s1", "s2", 70, 70, { workAreaId: "area-2" }),
    ]);
    expect(html).toContain("이전 결과와 비교");
    expect(html).toContain("깎임 4 m³ · 쌓임 1 m³");
    expect(html).toContain("깎임 3 m³ · 쌓임 9 m³");
    expect(html).not.toContain("50 m³");
    expect(html).not.toContain("60 m³");
    expect(html).not.toContain("70 m³");
    expect(html).toContain("같은 영역 · 임계값 0.1 m · 셀 1 m");
  });

  it("keeps only the latest recalculation of the same observation pair", () => {
    const html = renderTrend(view("now", "s2", "s3", 3, 9), [
      view("old-a", "s1", "s2", 4, 1, { createdAt: "2026-11-05T01:00:00Z" }),
      view("old-b", "s1", "s2", 5, 2, { createdAt: "2026-11-08T01:00:00Z" }),
    ]);
    expect(html).toContain("깎임 5 m³ · 쌓임 2 m³");
    expect(html).not.toContain("깎임 4 m³ · 쌓임 1 m³");
  });

  it("drops a result whose current observation date cannot be confirmed", () => {
    const html = renderTrend(view("now", "s2", "s3", 3, 9), [view("ghost", "s1", "s9", 8, 8)]);
    expect(html).toContain("비교할 수 있는 이전 결과가 없습니다");
    expect(html).not.toContain("깎임 8 m³");
  });

  it("says there is nothing to compare instead of drawing a lone bar", () => {
    const html = renderTrend(view("now", "s2", "s3", 3, 9), []);
    expect(html).toContain("비교할 수 있는 이전 결과가 없습니다");
    expect(html).not.toContain("<svg viewBox=\"0 0 100 120\"");
  });
});

describe("SiteWorkspaceResults same-day points", () => {
  it("adds the time to the axis label when two points share a date", () => {
    const sameDay = {
      ...trendFacts,
      observations: [
        baseObservation("e1", "s1", 1, 1),
        baseObservation("e2", "s2", 2, 1),
        { ...baseObservation("e3", "s3", 3, 1), captureEndedAt: "2026-11-01T06:30:00Z" },
      ],
    } as unknown as WorkspaceServerFacts;
    const focal = view("now", "s2", "s3", 3, 9);
    const html = renderToStaticMarkup(
      <SiteWorkspaceResults
        sitePath="/sites/site-1"
        areaLabel="1영역"
        areaAnalyses={[]}
        analysesKnown
        explicitResult={{ status: "ready", basis: "explicit", analysis: { analysisId: "now", workAreaId: "area-1", baseline: focal.baseline, current: focal.current } } as never}
        explicitDetail={focal}
        leadDetail={null}
        facts={sameDay}
        canCreateAnalysis={false}
        scopedCompareHref="/sites/site-1/analysis?workAreaId=area-1"
        visualContext={null}
        peerDetails={[view("old", "s1", "s2", 4, 1)]}
      />,
    );
    expect(html).toMatch(/11\.1 \d{1,2}:\d{2}/);
  });
});

describe("SiteWorkspaceResults compact pair line", () => {
  const render = (facts: WorkspaceServerFacts, focal: AnalysisView) =>
    renderToStaticMarkup(
      <SiteWorkspaceResults
        sitePath="/sites/site-1"
        areaLabel="1영역"
        areaAnalyses={[]}
        analysesKnown
        explicitResult={{ status: "ready", basis: "explicit", analysis: { analysisId: focal.analysisId, workAreaId: "area-1", baseline: focal.baseline, current: focal.current } } as never}
        explicitDetail={focal}
        leadDetail={null}
        facts={facts}
        canCreateAnalysis={false}
        scopedCompareHref="/sites/site-1/analysis?workAreaId=area-1"
        visualContext={null}
      />,
    );
  const old = (id: string, sub: string, order: number, iso: string) => ({
    ...baseObservation(id, sub, order, 1), captureEndedAt: iso,
  });

  it("writes one line and spells out the year when the dates are not both this year", () => {
    const facts = { ...trendFacts, observations: [old("e1", "s1", 1, "2021-10-06T03:30:00Z"), old("e2", "s2", 2, "2022-10-13T03:30:00Z")] } as unknown as WorkspaceServerFacts;
    const html = render(facts, view("now", "s1", "s2", 3, 9));
    expect(html).toMatch(/기준 2021\.10\.6 [^<]+ → 현재 2022\.10\.13 /);
    expect(html).not.toContain("원래 입력 일부");
  });

  it("warns only when an original input is missing from the current list", () => {
    const facts = { ...trendFacts, observations: [old("e1", "s1", 1, "2021-10-06T03:30:00Z")] } as unknown as WorkspaceServerFacts;
    const html = render(facts, view("now", "s1", "s9", 3, 9));
    expect(html).toContain("기준 2021.10.6");
    expect(html).toContain("현재 확인 불가");
    expect(html).toContain("원래 입력 일부를 현재 목록에서 확인할 수 없습니다");
  });
});

describe("SiteWorkspaceResults review state", () => {
  const focal = view("now", "s2", "s3", 3, 9);

  it("shows the latest recorded review decision", () => {
    const html = renderTrend(focal, [], { review: { status: "ready", count: 1, latest: { decision: "NEEDS_FOLLOW_UP", reviewedAt: "2026-11-10T01:00:00Z" } } });
    expect(html).toContain("검토됨 · 추가 확인 필요");
  });

  it("says no review only when the review list was actually read", () => {
    expect(renderTrend(focal, [], { review: { status: "ready", count: 0, latest: null } })).toContain("검토 기록 없음");
    const unread = renderTrend(focal, [], { review: { status: "unavailable" } });
    expect(unread).not.toContain("검토 기록 없음");
    expect(unread).not.toContain("검토됨");
    expect(renderTrend(focal, [], { review: null })).not.toContain("검토 기록 없음");
  });
});

describe("SiteWorkspaceResults coverage", () => {
  it("offers the grid reader without a background-map button", () => {
    const html = renderTrend(view("now", "s2", "s3", 3, 9), []);
    expect(html).toContain("계산·제외 영역 보기");
    expect(html).not.toContain("지도에서 계산 범위 보기");
    expect(html).toContain("계산 범위");
  });
});
