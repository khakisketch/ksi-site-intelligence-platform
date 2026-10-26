/** @vitest-environment jsdom */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SiteWorkspaceResults } from "@/app/sites/[siteId]/SiteWorkspaceResults";
import type { AnalysisView } from "@/lib/core-api/analysis";
import type { WorkspaceServerFacts } from "@/lib/site-workspace-entry";

/**
 * 명시적 기록(explicit analysisId) 분기의 회귀 — AnalysisPage의
 * "작업공간에서 결과 보기" 다리는 항상 analysisId를 싣고 오므로, 이 분기가
 * Core 수치를 빠뜨리면 성공한 결과가 목적지에서 수치를 잃는다.
 * 판정·재계산 없이 Core 기록을 옮기고, 잠정 값을 확정으로
 * 올리지 않으며, 모르는 값을 0으로 만들지 않는다.
 * (INV-024/053/061: 정확도 미확인 값을 보증으로 표시 금지, 미상 수치 0 대체 금지)
 */

function observation(overrides: Record<string, unknown> = {}) {
  return {
    observationEpochId: "epoch-base",
    workAreaId: "area-1",
    workOrderId: "w1",
    assetRef: "a-base",
    submissionRef: "s1",
    revision: 1,
    kind: "dsm",
    displayReady: true,
    inspectedRasterAvailable: true,
    chronologyCandidate: true,
    captureSourcesAgree: true,
    viewAvailable: true,
    viewUnavailableReason: null,
    viewAssetRef: "a-base",
    newerRevisionPending: false,
    newerRevisionState: null,
    captureStartedAt: "2026-10-25T03:00:00Z",
    captureEndedAt: "2026-10-25T03:30:00Z",
    captureDate: null,
    ...overrides,
  };
}

const facts = {
  siteId: "site-1",
  authorizedWorkAreaIds: ["area-1"],
  entryDefault: null,
  observations: [
    observation(),
    observation({
      observationEpochId: "epoch-cur",
      workOrderId: "w2",
      assetRef: "a-cur",
      submissionRef: "s2",
      viewAssetRef: "a-cur",
      captureStartedAt: "2026-10-26T03:00:00Z",
      captureEndedAt: "2026-10-26T03:30:00Z",
    }),
  ],
  analyses: [],
} as unknown as WorkspaceServerFacts;

const selectors = {
  analysisId: "analysis-9",
  workAreaId: "area-1",
  baseline: { workOrderId: "w1", submissionRef: "s1", revision: 1 },
  current: { workOrderId: "w2", submissionRef: "s2", revision: 1 },
};

const explicitResult = { status: "ready", basis: "explicit", analysis: selectors } as const;

function explicitDetail(overrides: Record<string, unknown> = {}): AnalysisView {
  return {
    analysisId: "analysis-9",
    siteId: "site-1",
    workAreaId: "area-1",
    baseline: { workOrderId: "w1", submissionRef: "s1", revision: 1 },
    current: { workOrderId: "w2", submissionRef: "s2", revision: 1 },
    executionState: "COMPLETED",
    suitabilityState: "PROVISIONAL_ACCURACY_UNVERIFIED",
    blockers: [],
    result: {
      resultId: "res-9",
      reportDigest: "rd",
      numericResultIdentityDigest: "nd",
      computedAt: "2026-10-25T10:25:00Z",
      metrics: { cutM3: 0.02, fillM3: 0.02, netM3: 0, thresholdM: 0.1, uncertaintyM3: null },
      coverage: {
        coverageWitnessDigest: "cw",
        rows: 1,
        columns: 1,
        selectedCellCount: 1,
        commonValidCellCount: 1,
        unavailableCellCount: 0,
        thresholdExcludedCellCount: 0,
        cellAreaM2: 1,
        selectedAreaM2: 1,
        commonValidAreaM2: 1,
        bounds: [0, 0, 1, 1],
      },
      limitationCodes: [],
    },
    evidenceRevision: 1,
    evidenceDigest: "ed",
    evidenceHref: "/evidence",
    coverageHref: null,
    createdAt: "2026-10-25T10:25:00Z",
    ...overrides,
  } as AnalysisView;
}

function renderResults(options: {
  detail?: AnalysisView | null;
  explicit?: typeof explicitResult | null;
  visualContext?: { workAreaId: string; visualAAssetRef: string; visualBAssetRef: string } | null;
  areaAnalyses?: Parameters<typeof SiteWorkspaceResults>[0]["areaAnalyses"];
}) {
  return renderToStaticMarkup(
    <SiteWorkspaceResults
      sitePath="/sites/site-1"
      areaLabel="1구역"
      areaAnalyses={options.areaAnalyses ?? []}
      analysesKnown
      explicitResult={options.explicit ?? explicitResult}
      explicitDetail={options.detail ?? explicitDetail()}
      leadDetail={null}
      facts={facts}
      canCreateAnalysis={false}
      scopedCompareHref="/sites/site-1/analysis?workAreaId=area-1"
      visualContext={options.visualContext ?? null}
    />,
  );
}

describe("site workspace explicit result metrics", () => {
  it("shows Core-recorded tiny quantities with explicit limits on the explicit branch", () => {
    const html = renderResults({});
    // 0.02가 소수 첫째 자리 반올림으로 0이 되지 않는다(AnalysisRequestPanel과 같은 규칙).
    expect(html.match(/0\.02 m³/g)?.length).toBeGreaterThanOrEqual(2);
    expect(html).toContain("절토");
    expect(html).toContain("성토");
    expect(html).toContain("순변화");
    expect(html).toContain("계산 수치 있음");
    // 잠정을 확정·보증으로 올리지 않는다.
    expect(html).not.toContain("확정된 수치");
    expect(html).toContain("정확도 평가는 아직 확인되지 않았습니다");
    expect(html).toContain("물량 정확도 보증·측량 승인·정산 근거가 아닙니다");
    // 같은 frozen 입력·날짜와 Core 근거 링크를 둔다.
    expect(html).toContain("원래 입력 2건이 현재 관측 목록에 있습니다");
    expect(html).toContain("analysisId=analysis-9");
    expect(html).toContain("자료·근거와 검토 보기");
  });

  it("shows no quantities and an honest next action when the explicit record has no result", () => {
    const html = renderResults({
      detail: explicitDetail({
        executionState: "COMPLETED",
        suitabilityState: "BLOCKED",
        blockers: [{ code: "ESSENTIAL_INPUT_UNAVAILABLE", epoch: "BASELINE", evidenceRef: null, detail: null }],
        result: null,
      }),
    });
    expect(html).toContain("계산 수치 없음");
    expect(html).not.toContain("확정된 수치");
    expect(html).toContain("이 기록에는 계산된 수치가 없습니다");
    // 결과가 없으면 수치를 두지 않는다 — 0 대체 금지.
    expect(html).not.toContain("m³");
    expect(html).not.toContain(">0<");
    // 다음 행동은 분석 기록 확인이다.
    expect(html).toContain("자료·근거와 검토 보기");
    // frozen 기록 자체는 그대로 둔다.
    expect(html).toContain("링크의 원래 기록을 그대로 보여줍니다");
  });

  it("keeps the frozen pair while the browsed pair stays a separate return", () => {
    const html = renderResults({
      visualContext: { workAreaId: "area-1", visualAAssetRef: "a-vis", visualBAssetRef: "b-vis" },
    });
    // frozen 입력(원래 기록 선택자)은 그대로 두고 탐색 쌍으로 바꾸지 않는다.
    expect(html).toContain("원래 입력 2건이 현재 관측 목록에 있습니다");
    expect(html).toContain("탐색 중 자료와 이 결과의 계산 입력은 다를 수 있습니다");
    expect(html).toContain("독립 보기로 돌아가기");
    expect(html).toContain("visualAAssetRef=a-vis");
    // frozen 근거 링크는 원래 기록 식별자를 유지한 채 탐색 복귀 맥락만 덧붙인다.
    const evidenceLink = html.split("자료·근거와 검토 보기")[0]!.split("<a ").pop() ?? "";
    expect(evidenceLink).toContain("analysisId=analysis-9");
    expect(html).toContain("0.02 m³");
  });

  it("formats tiny default-card quantities like the canonical request panel", () => {
    const html = renderResults({
      explicit: null,
      detail: null,
      areaAnalyses: [{
        analysisId: "a1",
        siteId: "site-1",
        workAreaId: "area-1",
        executionState: "COMPLETED",
        suitabilityState: "PROVISIONAL_ACCURACY_UNVERIFIED",
        createdAt: "2026-10-25T10:25:00Z",
        resultId: "res-1",
        metrics: { cutM3: 0.02, fillM3: 0.02, netM3: 0, thresholdM: 0.1, uncertaintyM3: null },
        limitationCount: 0,
        analysisHref: "/sites/site-1/analysis?workAreaId=area-1&analysisId=a1",
      }],
    });
    expect(html.match(/0\.02 m³/g)?.length).toBeGreaterThanOrEqual(2);
    expect(html).not.toContain("확정된 수치");
    expect(html).toContain("정확도 평가는 아직 확인되지 않았습니다");
    expect(html).toContain("물량 정확도 보증·측량 승인·정산 근거가 아닙니다");
  });
});
