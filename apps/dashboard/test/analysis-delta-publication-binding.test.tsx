/** @vitest-environment jsdom */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AnalysisReviewTarget, AnalysisView } from "@/lib/core-api/analysis";
import { AnalysisDeltaPublication, boundDeltaPublicationSource } from "@/app/sites/[siteId]/analysis/AnalysisDeltaPublication";

const shown = vi.hoisted(() => vi.fn());
vi.mock("@/app/sites/[siteId]/analysis/DeltaPublicationPanel", () => ({
  DeltaPublicationPanel: (props: unknown) => { shown(props); return <section>출처가 묶인 파일 요청</section>; },
}));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

const digest = (letter: string) => `sha256:${letter.repeat(64)}`;
const detail = {
  analysisId: "analysis-1", siteId: "site-a", workAreaId: "area-a", executionState: "COMPLETED",
  result: { resultId: "result-1", reportDigest: digest("a"), numericResultIdentityDigest: digest("b"),
    coverage: { coverageWitnessDigest: digest("c") } },
} as AnalysisView;
const target = {
  resultId: "result-1", reportDigest: digest("a"), numericResultIdentityDigest: digest("b"),
  calculationIdentityDigest: digest("d"),
} as AnalysisReviewTarget;
const delivery = { lifetimeSeconds: 120, downloadBudgetBytes: 1_000_000 };

describe("result-bound export source", () => {
  it("uses only the exact Core target plus the existing coverage witness", () => {
    expect(boundDeltaPublicationSource(detail, "analysis-1", target)).toEqual({
      sourceCalculationIdentityDigest: digest("d"), sourceNumericResultIdentityDigest: digest("b"),
      sourceCoverageWitnessDigest: digest("c"),
    });
  });

  it.each(["analysis", "result", "report", "numeric", "calculation", "coverage", "unfinished"])(
    "does not borrow a %s fact from another result or invent it",
    (change) => {
      const current = structuredClone(detail);
      const review = { ...target };
      let analysis = "analysis-1";
      if (change === "analysis") analysis = "analysis-other";
      if (change === "result") review.resultId = "other";
      if (change === "report") review.reportDigest = digest("e");
      if (change === "numeric") review.numericResultIdentityDigest = digest("e");
      if (change === "calculation") review.calculationIdentityDigest = "missing";
      if (change === "coverage") current.result!.coverage.coverageWitnessDigest = "missing";
      if (change === "unfinished") current.executionState = "RUNNING";
      expect(boundDeltaPublicationSource(current, analysis, review)).toBeNull();
    },
  );

  it("shows honest unconfigured delivery without requesting anything", () => {
    render(<AnalysisDeltaPublication detail={detail} workAreaLabel="구역" canRequest delivery={null}
      reviewAnalysisId="analysis-1" target={target} sourceLoading={false} />);
    expect(screen.getByText(/이 환경에는 차분 파일 내보내기가 연결되지 않았습니다/)).toBeTruthy();
    expect(shown).not.toHaveBeenCalled();
  });

  it("does not display a configured export until the result's exact target is available", () => {
    const view = render(<AnalysisDeltaPublication detail={detail} workAreaLabel="구역" canRequest
      delivery={delivery} reviewAnalysisId={null} target={null} sourceLoading />);
    expect(screen.getByText(/결과 출처를 확인하고 있습니다/)).toBeTruthy();
    expect(shown).not.toHaveBeenCalled();
    view.rerender(<AnalysisDeltaPublication detail={detail} workAreaLabel="구역" canRequest
      delivery={delivery} reviewAnalysisId="analysis-1" target={target} sourceLoading={false} />);
    expect(shown).toHaveBeenLastCalledWith(expect.objectContaining({
      siteId: "site-a", workAreaId: "area-a", lifetimeSeconds: 120, downloadBudgetBytes: 1_000_000,
      source: expect.objectContaining({ sourceCalculationIdentityDigest: digest("d") }),
    }));
  });
});
