import type { ExternalPendingDecision } from "@/lib/core-api/external-decisions";
import { formatNetVolumeM3, formatVolumeM3 } from "@/lib/core-api/phase34-labels";

/** Home card text derived only from values recorded by Core. */
export function externalDecisionCardText(decision: ExternalPendingDecision): {
  label: string;
  title: string;
  detail: string;
  href: string;
  actionLabel: string;
} {
  const review = decision.stage === "AWAITING_REVIEW";
  const uncertainty = decision.uncertaintyM3 === null
    ? "불확도 미산출"
    : `불확도 ±${formatVolumeM3(decision.uncertaintyM3)}`;
  return {
    label: review ? "외부 결과 · 검토 대기" : "외부 결과 · 승인 대기",
    title: `순 체적 ${formatNetVolumeM3(decision.netM3)} · ${uncertainty}`,
    detail: review
      ? "측정 결과와 근거를 검토하고 사용 여부를 결정하세요."
      : "검토한 결과로 만든 재관측 제안이 승인을 기다립니다.",
    href: `/sites/${encodeURIComponent(decision.siteId)}/observations/${encodeURIComponent(decision.reportRef)}`,
    actionLabel: "결과와 근거 보기",
  };
}
