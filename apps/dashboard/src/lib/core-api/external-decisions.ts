import "server-only";

import { coreFetch } from "./client";

/**
 * AX-4: 사람이 판단할 외부 결과 한 건(현장당 하나). 대기 여부는 Core 가 원장에서
 * 계산한다 — 검토 영수증이 없는 성공 측정은 검토 대기, 승인 영수증이 없는 재관측
 * 제안은 승인 대기다. 화면은 이 값을 추정하지 않는다(ADR-KSI-025 D1).
 */
export interface ExternalPendingDecision {
  siteId: string;
  reportRef: string;
  kind: "EXTERNAL_RELATIVE_VOLUME" | "EXTERNAL_SINGLE_VOLUME";
  stage: "AWAITING_REVIEW" | "AWAITING_APPROVAL";
  reportedAt: string;
  netM3: number;
  uncertaintyM3: number | null;
  workAreaId: string;
}

export async function listExternalPendingDecisions(): Promise<{ items: ExternalPendingDecision[] }> {
  return coreFetch<{ items: ExternalPendingDecision[] }>("/v1/external-decisions/pending");
}
