"use client";

import type { AnalysisReviewTarget, AnalysisView } from "@/lib/core-api/analysis";
import type { DeltaExportDeliveryConfig } from "@/lib/delta-export-config";

import { DeltaPublicationPanel, type DeltaPublicationSource } from "./DeltaPublicationPanel";

/** A review's target is also an exact read-only Core result binding, not approval. */
export function boundDeltaPublicationSource(
  detail: AnalysisView,
  reviewAnalysisId: string | null,
  target: AnalysisReviewTarget | null,
): DeltaPublicationSource | null {
  const result = detail.result;
  if (detail.executionState !== "COMPLETED" || !result || !target
    || reviewAnalysisId !== detail.analysisId
    || target.resultId !== result.resultId || target.reportDigest !== result.reportDigest
    || target.numericResultIdentityDigest !== result.numericResultIdentityDigest) return null;
  const values = [target.calculationIdentityDigest, result.numericResultIdentityDigest,
    result.coverage?.coverageWitnessDigest];
  if (!values.every((value) => typeof value === "string" && /^sha256:[0-9a-f]{64}$/.test(value))) return null;
  return {
    sourceCalculationIdentityDigest: values[0]!,
    sourceNumericResultIdentityDigest: values[1]!,
    sourceCoverageWitnessDigest: values[2]!,
  };
}

export function AnalysisDeltaPublication({ detail, workAreaLabel, canRequest, delivery,
  reviewAnalysisId, target, sourceLoading }: {
  detail: AnalysisView;
  workAreaLabel: string;
  canRequest: boolean;
  delivery: DeltaExportDeliveryConfig | null;
  reviewAnalysisId: string | null;
  target: AnalysisReviewTarget | null;
  sourceLoading: boolean;
}) {
  const source = boundDeltaPublicationSource(detail, reviewAnalysisId, target);
  if (!delivery || !source) return <section aria-label="차분 파일" className="border-t border-line px-4 py-3">
    <h3 className="text-[13px] font-semibold">차분 파일</h3>
    <p className="mt-1 text-[12px] leading-5 text-ink-2">
      {!delivery ? "이 환경에는 차분 파일 내보내기가 연결되지 않았습니다."
        : sourceLoading ? "파일에 사용할 결과 출처를 확인하고 있습니다."
          : "파일에 사용할 결과 출처를 확인하지 못했습니다."}
      {" "}수치 결과와 근거 기록은 별도로 유지됩니다.
    </p>
  </section>;
  return <DeltaPublicationPanel
    key={[detail.analysisId, source.sourceCalculationIdentityDigest,
      source.sourceNumericResultIdentityDigest, source.sourceCoverageWitnessDigest].join(":")}
    siteId={detail.siteId} workAreaId={detail.workAreaId} workAreaLabel={workAreaLabel}
    source={source} canRequest={canRequest} lifetimeSeconds={delivery.lifetimeSeconds}
    downloadBudgetBytes={delivery.downloadBudgetBytes}
  />;
}
