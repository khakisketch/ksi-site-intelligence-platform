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

/**
 * Home 분석-검토 읽기의 현장별 판정 — 성공적 빈(empty)·보류(pending)와
 * 미확인(unknown)을 구분한다. 실패·거부·범위 초과는 비어 있음도 검토 완료도
 * 아니다(ADR-KSI-025 D1 unknown-not-0): 관찰하지 않은 나머지를 0이라
 * 주장하지 않는다.
 */
export type HomeAnalysisReviewSiteRead =
  | { status: "pending"; source: HomeAnalysisReviewSource }
  | { status: "clear"; siteId: string }
  | { status: "unknown"; siteId: string };

/** 현장별 판정을 Home 표시용으로 접는다 — 보류는 그대로 보여주고, 미확인은
 *  건수·무안건 결론에서 뺀다(표시는 남고 건수는 "—"가 된다). */
export function summarizeHomeAnalysisReviewReads(
  reads: readonly HomeAnalysisReviewSiteRead[],
  outOfScopeSiteIds: readonly string[] = [],
): { sources: HomeAnalysisReviewSource[]; unknownSiteIds: string[] } {
  return {
    sources: reads.flatMap((read) => (read.status === "pending" ? [read.source] : [])),
    unknownSiteIds: [
      ...outOfScopeSiteIds,
      ...reads.flatMap((read) => (read.status === "unknown" ? [read.siteId] : [])),
    ],
  };
}

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

/**
 * 대기열·초기 설정에 오르지 않은 실제 현장 바로가기 — 이미 드러난 현장은
 * 빼고, 하나도 남지 않으면 빈 배열을 둔다. 장식·추측 항목을 만들지 않는다.
 */
export function selectHomeQuickAccessSites(
  sites: readonly SiteView[],
  surfacedSiteIds: ReadonlySet<string>,
): SiteView[] {
  return sites.filter((site) => !surfacedSiteIds.has(site.siteId));
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
