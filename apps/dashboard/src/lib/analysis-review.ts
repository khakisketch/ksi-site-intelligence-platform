import type { AnalysisReviewReceipt, AnalysisReviewTarget } from "@/lib/core-api/analysis";

/** Shared exact-result comparison used by both Home attention and the review panel. */
export function sameAnalysisReviewTarget(left: AnalysisReviewTarget, right: AnalysisReviewTarget): boolean {
  return left.resultId === right.resultId
    && left.resultRevision === right.resultRevision
    && left.reportDigest === right.reportDigest
    && left.numericResultIdentityDigest === right.numericResultIdentityDigest
    && left.calculationIdentityDigest === right.calculationIdentityDigest
    && left.admissionDigest === right.admissionDigest
    && left.evaluations.every((evaluation, index) => {
      const other = right.evaluations[index];
      return other !== undefined
        && evaluation.epoch === other.epoch
        && evaluation.evaluationId === other.evaluationId
        && evaluation.revision === other.revision
        && evaluation.evaluationDigest === other.evaluationDigest;
    });
}

/**
 * Core review pages are not guaranteed to be newest-first. Keep the panel's timestamp
 * selection rule in one place so callers evaluate the latest receipt consistently.
 */
export function latestAnalysisReview(items: readonly AnalysisReviewReceipt[]): AnalysisReviewReceipt | null {
  return items.reduce<AnalysisReviewReceipt | null>((latest, item) => {
    if (!latest) return item;
    const latestTime = Date.parse(latest.reviewedAt);
    const currentTime = Date.parse(item.reviewedAt);
    return Number.isFinite(currentTime) && (!Number.isFinite(latestTime) || currentTime > latestTime) ? item : latest;
  }, null);
}
