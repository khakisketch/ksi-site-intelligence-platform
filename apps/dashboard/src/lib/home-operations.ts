import type { AnalysisListItem, AnalysisReviewReceipt, AnalysisReviewTarget } from "@/lib/core-api/analysis";
import type { ExternalPendingDecision } from "@/lib/core-api/external-decisions";
import type {
  ObservationWorkOrderOperationsView,
  ObservationWorkOrderStatus,
  ObservationWorkOrderView,
  SiteView,
} from "@/lib/core-api/types";
import { latestAnalysisReview, sameAnalysisReviewTarget } from "@/lib/analysis-review";

const DECISION_PRIORITY: Readonly<Record<ObservationWorkOrderStatus, number | null>> = {
  BLOCKED: 0,
  DRAFT: 1,
  AWAITING_APPROVAL: 1,
  REOBSERVATION_PENDING: 2,
  REVIEW_READY: 3,
  APPROVED: null,
  DISPATCHED: null,
  START_REPORTED: null,
  MEDIA_RECEIVING: null,
  PROCESSING: null,
  COMPLETED: null,
  CANCELLED: null,
};

const ACTIVE_STATUSES = new Set<ObservationWorkOrderStatus>([
  "APPROVED", "DISPATCHED", "START_REPORTED", "MEDIA_RECEIVING", "PROCESSING",
]);

function newestFirst(a: ObservationWorkOrderView, b: ObservationWorkOrderView): number {
  return b.updatedAt.localeCompare(a.updatedAt);
}

export interface HomeWorkOrderOperationOptions {
  operationsByWorkOrderId?: ReadonlyMap<string, Pick<ObservationWorkOrderOperationsView, "workflowStatus">>;
}

function isVisibleOperationalWorkOrder(workOrder: ObservationWorkOrderView, options: HomeWorkOrderOperationOptions): boolean {
  const operations = options.operationsByWorkOrderId?.get(workOrder.workOrderId);
  if (operations?.workflowStatus === "CLOSED") return false;
  return workOrder.executionMode !== "EXTERNAL_RECONSTRUCTION" || operations?.workflowStatus === "OPEN";
}

export function selectHomeDecisionWorkOrders(
  workOrders: readonly ObservationWorkOrderView[],
  limit: number,
  options: HomeWorkOrderOperationOptions = {},
): ObservationWorkOrderView[] {
  return workOrders
    .filter((workOrder) => isVisibleOperationalWorkOrder(workOrder, options) && DECISION_PRIORITY[workOrder.status] !== null)
    .toSorted((a, b) => {
      const priority = (DECISION_PRIORITY[a.status] ?? Number.MAX_SAFE_INTEGER) - (DECISION_PRIORITY[b.status] ?? Number.MAX_SAFE_INTEGER);
      return priority !== 0 ? priority : newestFirst(a, b);
    })
    .slice(0, limit);
}

export function selectHomeActiveWorkOrders(
  workOrders: readonly ObservationWorkOrderView[],
  limit: number,
  options: HomeWorkOrderOperationOptions = {},
): ObservationWorkOrderView[] {
  return workOrders.filter((workOrder) => isVisibleOperationalWorkOrder(workOrder, options) && ACTIVE_STATUSES.has(workOrder.status))
    .toSorted(newestFirst)
    .slice(0, limit);
}

export type HomeAttentionSource =
  | { kind: "EXTERNAL_DECISION"; key: string; siteId: string; observedAt: string; decision: ExternalPendingDecision }
  | { kind: "ANALYSIS_REVIEW"; key: string; siteId: string; observedAt: string; analysis: AnalysisListItem }
  | { kind: "WORK_ORDER"; key: string; siteId: string; observedAt: string; workOrder: ObservationWorkOrderView }
  | { kind: "SITE"; key: string; siteId: string; observedAt: string; site: SiteView };

export type HomeAnalysisReviewSource = Extract<HomeAttentionSource, { kind: "ANALYSIS_REVIEW" }>;

export type HomeAnalysisReviewRecord = {
  analysis: AnalysisListItem;
  currentTarget: AnalysisReviewTarget;
  reviews: readonly AnalysisReviewReceipt[];
};

/** Select the newest completed analysis per Site with no review for its exact current result. */
export function selectHomeAnalysisReviewSources(records: readonly HomeAnalysisReviewRecord[]): HomeAnalysisReviewSource[] {
  const pending = records.flatMap((record) => {
    if (record.analysis.executionState !== "COMPLETED" || record.analysis.resultId === null) return [];
    const latest = latestAnalysisReview(record.reviews);
    if (latest && sameAnalysisReviewTarget(latest.target, record.currentTarget)) return [];
    return [record];
  }).toSorted((a, b) => b.analysis.createdAt.localeCompare(a.analysis.createdAt)
    || a.analysis.analysisId.localeCompare(b.analysis.analysisId));

  const selectedSites = new Set<string>();
  return pending.flatMap(({ analysis }) => {
    if (selectedSites.has(analysis.siteId)) return [];
    selectedSites.add(analysis.siteId);
    return [{
      kind: "ANALYSIS_REVIEW" as const,
      key: `analysis-review:${analysis.analysisId}`,
      siteId: analysis.siteId,
      observedAt: analysis.createdAt,
      analysis,
    }];
  });
}

export function selectHomeInitialSetupSites(
  sites: readonly SiteView[],
  limit = 3,
  context?: { workOrders: readonly ObservationWorkOrderView[]; known: boolean },
): SiteView[] {
  // Legacy Site state alone does not prove that an already-used Site needs setup.
  // Unknown work reads must not be interpreted as "no observations yet".
  if (context && !context.known) return [];
  const usedSiteIds = new Set(context?.workOrders.map((order) => order.siteId) ?? []);
  return sites.filter((site) => site.status === "UNMAPPED" && !usedSiteIds.has(site.siteId))
    .toSorted((a, b) => a.updatedAt.localeCompare(b.updatedAt) || a.siteId.localeCompare(b.siteId))
    .slice(0, limit);
}

export interface HomeRecentSiteSource {
  key: string;
  siteId: string;
  observedAt: string;
  site: SiteView;
}

export function selectHomeRecentSiteSources(sites: readonly SiteView[], limit = 3): HomeRecentSiteSource[] {
  return sites.map((site) => ({ key: `recent-site:${site.siteId}`, siteId: site.siteId, observedAt: site.updatedAt, site }))
    .toSorted((a, b) => Number(a.site.status === "UNMAPPED") - Number(b.site.status === "UNMAPPED")
      || b.observedAt.localeCompare(a.observedAt) || a.siteId.localeCompare(b.siteId))
    .slice(0, limit);
}

export function selectHomeAttentionSources(input: {
  workOrders: readonly ObservationWorkOrderView[];
  sites: readonly SiteView[];
  operationsByWorkOrderId?: HomeWorkOrderOperationOptions["operationsByWorkOrderId"];
  externalDecisions?: readonly ExternalPendingDecision[];
  analysisReviews?: readonly HomeAnalysisReviewSource[];
}, limit = 3): HomeAttentionSource[] {
  const candidates: HomeAttentionSource[] = [
    ...(input.externalDecisions ?? []).map((decision) => ({
      kind: "EXTERNAL_DECISION" as const, key: `external-decision:${decision.reportRef}`,
      siteId: decision.siteId, observedAt: decision.reportedAt, decision,
    })),
    ...(input.analysisReviews ?? []).toSorted((a, b) => b.observedAt.localeCompare(a.observedAt) || a.key.localeCompare(b.key)),
    ...selectHomeDecisionWorkOrders(input.workOrders, input.workOrders.length, {
      operationsByWorkOrderId: input.operationsByWorkOrderId,
    }).map((workOrder) => ({ kind: "WORK_ORDER" as const, key: `work-order:${workOrder.workOrderId}`, siteId: workOrder.siteId, observedAt: workOrder.updatedAt, workOrder })),
    ...input.sites.filter((site) => ["UNMAPPED", "REMAP_REQUIRED", "MODEL_STALE"].includes(site.status))
      .toSorted((a, b) => a.updatedAt.localeCompare(b.updatedAt))
      .map((site) => ({ kind: "SITE" as const, key: `site:${site.siteId}`, siteId: site.siteId, observedAt: site.updatedAt, site })),
  ];
  const selected: HomeAttentionSource[] = [];
  const selectedSites = new Set<string>();
  for (const candidate of candidates) {
    if (selectedSites.has(candidate.siteId)) continue;
    selected.push(candidate);
    selectedSites.add(candidate.siteId);
    if (selected.length >= limit) break;
  }
  return selected;
}

export type HomeRecentUpdateSource = {
  kind: "RESULT_READY" | "OBSERVATION_COMPLETED";
  key: string;
  siteId: string;
  observedAt: string;
  workOrder: ObservationWorkOrderView;
} | {
  kind: "CURRENT_LEDGER_CLEAR";
  key: string;
  siteId: string;
  observedAt: string;
  site: SiteView;
};

export function selectHomeRecentUpdates(input: {
  workOrders: readonly ObservationWorkOrderView[];
  sites: readonly SiteView[];
  excludedSiteIds?: ReadonlySet<string>;
}, limit = 2): HomeRecentUpdateSource[] {
  const excluded = input.excludedSiteIds ?? new Set<string>();
  const candidates: HomeRecentUpdateSource[] = input.workOrders
    .filter((workOrder) => workOrder.status === "REVIEW_READY" || workOrder.status === "COMPLETED")
    .map((workOrder) => ({
      kind: workOrder.status === "REVIEW_READY" ? "RESULT_READY" as const : "OBSERVATION_COMPLETED" as const,
      key: `work-order:${workOrder.workOrderId}`, siteId: workOrder.siteId,
      observedAt: workOrder.updatedAt, workOrder,
    }))
    .toSorted((a, b) => b.observedAt.localeCompare(a.observedAt) || a.key.localeCompare(b.key));
  const selected: HomeRecentUpdateSource[] = [];
  const selectedSites = new Set(excluded);
  for (const candidate of candidates) {
    if (selectedSites.has(candidate.siteId)) continue;
    selected.push(candidate);
    selectedSites.add(candidate.siteId);
    if (selected.length >= limit) return selected;
  }
  for (const site of input.sites.filter((item) => !selectedSites.has(item.siteId)).toSorted((a, b) => b.updatedAt.localeCompare(a.updatedAt))) {
    selected.push({ kind: "CURRENT_LEDGER_CLEAR", key: `site:${site.siteId}`, siteId: site.siteId, observedAt: site.updatedAt, site });
    if (selected.length >= limit) break;
  }
  return selected;
}
