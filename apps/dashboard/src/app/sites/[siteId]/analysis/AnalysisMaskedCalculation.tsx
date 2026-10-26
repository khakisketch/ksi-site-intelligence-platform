"use client";

import { useState } from "react";
import type { AnalysisEvidencePage, AnalysisView } from "@/lib/core-api/analysis";
import type { MaskedCalculationDetailWire } from "@/lib/core-api/masked-analysis";
import type { DeltaExportDeliveryConfig } from "@/lib/delta-export-config";
import { boundMaskedSourceIdentity } from "@/lib/masked-source-binding";
import { DeltaPublicationPanel, type DeltaPublicationSource } from "./DeltaPublicationPanel";
import { MaskedAnalysisPanel } from "./MaskedAnalysisPanel";

export function boundMaskedOutputSource(sourceIdentity: string, result: MaskedCalculationDetailWire | null,
  siteId: string, workAreaId: string): DeltaPublicationSource | null {
  const report = result?.report;
  const admission = result?.admission;
  if (!result || !report || !admission || result.disposition !== "AVAILABLE"
    || result.status !== "COMPLETED" || result.siteId !== siteId || result.workAreaId !== workAreaId
    || admission.sourceCalculationIdentityDigest !== sourceIdentity
    || admission.maskedCalculationIdentityDigest !== result.maskedCalculationIdentityDigest
    || report.maskedCalculationIdentityDigest !== result.maskedCalculationIdentityDigest
    || report.numericResult.maskedCalculationIdentityDigest !== result.maskedCalculationIdentityDigest
    || report.numericResult.numericResultIdentityDigest !== report.numericResultIdentityDigest) return null;
  const values = [result.maskedCalculationIdentityDigest, report.numericResultIdentityDigest,
    report.numericResult.coverage.coverageWitnessDigest, report.reportDigest];
  if (!values.every((value) => typeof value === "string" && /^sha256:[0-9a-f]{64}$/.test(value))) return null;
  return { sourceCalculationIdentityDigest: values[0]!, sourceNumericResultIdentityDigest: values[1]!,
    sourceCoverageWitnessDigest: values[2]! };
}

export function AnalysisMaskedCalculation({ detail, pages, workAreaName, canRequest, maskBudgetBytes, delivery, sessionScope = null, onLoadSource, sourceLoading = false }: {
  detail: AnalysisView; pages: readonly AnalysisEvidencePage[]; workAreaName: string; canRequest: boolean;
  maskBudgetBytes: number | null; delivery: DeltaExportDeliveryConfig | null;
  sessionScope?: { organizationId: string; principalId: string } | null;
  onLoadSource?: () => void; sourceLoading?: boolean;
}) {
  const sourceIdentity = boundMaskedSourceIdentity(detail, pages);
  return <details className="border-t border-line px-4 py-3">
    <summary className="tap-target cursor-pointer text-[13px] font-semibold">독립 마스크로 별도 계산 · V3</summary>
    <p className="mb-3 mt-2 text-[12px] leading-5 text-ink-2">기존 결과는 유지하고, 마스크로 제외할 셀을 지정해 별도 계산합니다. 마스크 등록·검사가 정확도 보증을 만들지는 않습니다.</p>
    {!sourceIdentity && onLoadSource && <div className="mb-3">
      <p className="mb-2 text-[12px] text-ink-2">먼저 이 분석 기록의 원본 근거를 불러오세요. 읽기만 하며 계산을 시작하지 않습니다.</p>
      <button type="button" className="btn" disabled={sourceLoading} onClick={onLoadSource}>
        {sourceLoading ? "원본 근거 불러오는 중" : "원본 근거 불러오기"}
      </button>
    </div>}
    <BoundMaskedWorkflow key={`${sessionScope?.organizationId ?? ""}:${sessionScope?.principalId ?? ""}:${detail.analysisId}:${sourceIdentity ?? "unresolved"}`}
      sourceIdentity={sourceIdentity} siteId={detail.siteId} workAreaId={detail.workAreaId}
      workAreaName={workAreaName} canRequest={canRequest} maskBudgetBytes={maskBudgetBytes} delivery={delivery} sessionScope={sessionScope} />
  </details>;
}

function BoundMaskedWorkflow({ sourceIdentity, siteId, workAreaId, workAreaName, canRequest, maskBudgetBytes, delivery, sessionScope }: {
  sourceIdentity: string | null; siteId: string; workAreaId: string; workAreaName: string;
  canRequest: boolean; maskBudgetBytes: number | null; delivery: DeltaExportDeliveryConfig | null;
  sessionScope: { organizationId: string; principalId: string } | null;
}) {
  const [current, setCurrent] = useState<MaskedCalculationDetailWire | null>(null);
  const output = sourceIdentity ? boundMaskedOutputSource(sourceIdentity, current, siteId, workAreaId) : null;
  return <>
    <MaskedAnalysisPanel siteId={siteId} workAreaId={workAreaId} workAreaName={workAreaName}
      canRequest={canRequest} sourceCalculationIdentityDigest={sourceIdentity} maskBudgetBytes={maskBudgetBytes}
      initialChild={null} initialCalculation={null} onResult={setCurrent} onInvalidated={() => setCurrent(null)} sessionScope={sessionScope} />
    {output && delivery && <DeltaPublicationPanel
      key={`${output.sourceCalculationIdentityDigest}:${output.sourceNumericResultIdentityDigest}`}
      siteId={siteId} workAreaId={workAreaId} workAreaLabel={`${workAreaName} · 독립 마스크 V3`}
      source={output} canRequest={canRequest} lifetimeSeconds={delivery.lifetimeSeconds}
      downloadBudgetBytes={delivery.downloadBudgetBytes} />}
    {output && !delivery && <p className="mt-2 text-[12px] text-ink-2">마스크 수치 결과는 유지됩니다. 이 환경에는 차분 파일 내보내기가 연결되지 않았습니다.</p>}
  </>;
}
