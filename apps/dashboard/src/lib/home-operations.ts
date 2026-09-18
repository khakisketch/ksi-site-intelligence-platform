import type { ExternalPendingDecision } from "@/lib/core-api/external-decisions";
import { isSettled, isUnattended, sortForTriage } from "@/lib/core-api/triage";
import type {
  SiteBriefing,
  EventSummaryResponse,
  ObservationWorkOrderOperationsView,
  ObservationWorkOrderStatus,
  ObservationWorkOrderView,
  SiteView,
} from "@/lib/core-api/types";

/**
 * 홈은 모든 작업을 복제하지 않고, 사람이 다음에 판단할 작업과 진행을 지켜볼 작업만
 * 나눈다. 상태값을 화면마다 따로 분류하면 /field 와 Home 이 다른 우선순위를 말하게
 * 되므로 이 선택 규칙을 한 곳에 둔다.
 */
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
  "APPROVED",
  "DISPATCHED",
  "START_REPORTED",
  "MEDIA_RECEIVING",
  "PROCESSING",
]);

function newestFirst(a: ObservationWorkOrderView, b: ObservationWorkOrderView): number {
  return b.updatedAt.localeCompare(a.updatedAt);
}

export interface HomeWorkOrderOperationOptions {
  /**
   * External work is operationally active only after the separate operations
   * projection confirms OPEN. A missing/legacy projection is not guessed.
   */
  operationsByWorkOrderId?: ReadonlyMap<string, Pick<ObservationWorkOrderOperationsView, "workflowStatus">>;
}

function isVisibleOperationalWorkOrder(
  workOrder: ObservationWorkOrderView,
  options: HomeWorkOrderOperationOptions,
): boolean {
  const operations = options.operationsByWorkOrderId?.get(workOrder.workOrderId);
  // Closure wins even for retained legacy external successors whose durable
  // WorkOrder predates executionMode.
  if (operations?.workflowStatus === "CLOSED") return false;
  return workOrder.executionMode !== "EXTERNAL_RECONSTRUCTION"
    || operations?.workflowStatus === "OPEN";
}

/** 사람이 검토·승인·복구해야 하는 작업만, 실제 workflow 우선순위 순으로 고른다. */
export function selectHomeDecisionWorkOrders(
  workOrders: readonly ObservationWorkOrderView[],
  limit: number,
  options: HomeWorkOrderOperationOptions = {},
): ObservationWorkOrderView[] {
  return workOrders
    .filter((workOrder) => (
      isVisibleOperationalWorkOrder(workOrder, options)
      && DECISION_PRIORITY[workOrder.status] !== null
    ))
    .toSorted((a, b) => {
      const priorityDifference =
        (DECISION_PRIORITY[a.status] ?? Number.MAX_SAFE_INTEGER) -
        (DECISION_PRIORITY[b.status] ?? Number.MAX_SAFE_INTEGER);
      return priorityDifference !== 0 ? priorityDifference : newestFirst(a, b);
    })
    .slice(0, limit);
}

/** 진행 중인 작업은 결정 대기와 섞지 않는다. 최신 갱신 순으로만 보여 준다. */
export function selectHomeActiveWorkOrders(
  workOrders: readonly ObservationWorkOrderView[],
  limit: number,
  options: HomeWorkOrderOperationOptions = {},
): ObservationWorkOrderView[] {
  return workOrders
    .filter((workOrder) => isVisibleOperationalWorkOrder(workOrder, options) && ACTIVE_STATUSES.has(workOrder.status))
    .toSorted(newestFirst)
    .slice(0, limit);
}

export type HomeAttentionSource =
  | { kind: "EVENT"; key: string; siteId: string; observedAt: string; event: EventSummaryResponse }
  | { kind: "EXTERNAL_DECISION"; key: string; siteId: string; observedAt: string; decision: ExternalPendingDecision }
  | { kind: "WORK_ORDER"; key: string; siteId: string; observedAt: string; workOrder: ObservationWorkOrderView }
  | { kind: "SITE"; key: string; siteId: string; observedAt: string; site: SiteView };

/** Home의 별도 준비 구역에 표시할 최초 설정 현장만 고른다. */
export function selectHomeInitialSetupSites(
  sites: readonly SiteView[],
  limit = 3,
): SiteView[] {
  return sites
    .filter((site) => site.status === "UNMAPPED")
    .toSorted((a, b) => {
      const byUpdatedAt = a.updatedAt.localeCompare(b.updatedAt);
      return byUpdatedAt !== 0 ? byUpdatedAt : a.siteId.localeCompare(b.siteId);
    })
    .slice(0, limit);
}

export interface HomeRecentSiteSource {
  key: string;
  siteId: string;
  observedAt: string;
  site: SiteView;
  latestEvent: EventSummaryResponse | null;
}

/**
 * 새 운영 안건이 없을 때도 Home의 시각 무대를 유지할 최근 현장을 고른다.
 * 초기 설정 현장은 운영 중인 현장 뒤에 두고, 각 현장의 가장 최근 실제 Event만
 * 이미지 근거 후보로 연결한다.
 */
export function selectHomeRecentSiteSources(
  input: {
    events: readonly EventSummaryResponse[];
    sites: readonly SiteView[];
  },
  limit = 3,
): HomeRecentSiteSource[] {
  const latestEventBySite = new Map<string, EventSummaryResponse>();
  for (const event of input.events.toSorted((a, b) => b.receivedAt.localeCompare(a.receivedAt))) {
    if (!latestEventBySite.has(event.siteId)) latestEventBySite.set(event.siteId, event);
  }

  return input.sites
    .map((site): HomeRecentSiteSource => {
      const latestEvent = latestEventBySite.get(site.siteId) ?? null;
      return {
        key: `recent-site:${site.siteId}`,
        siteId: site.siteId,
        observedAt: latestEvent?.occurredAt ?? site.updatedAt,
        site,
        latestEvent,
      };
    })
    .toSorted((a, b) => {
      const setupDifference = Number(a.site.status === "UNMAPPED") - Number(b.site.status === "UNMAPPED");
      if (setupDifference !== 0) return setupDifference;
      const byObservedAt = b.observedAt.localeCompare(a.observedAt);
      return byObservedAt !== 0 ? byObservedAt : a.siteId.localeCompare(b.siteId);
    })
    .slice(0, limit);
}

/**
 * 경영·다현장 Home의 "확인이 필요한 현장" 후보를 실제 원장 사실에서만 고른다.
 * 같은 현장에 사건과 작업이 여럿 있어도 Home에서는 가장 우선인 한 장만 보여 주고,
 * 세부 원장은 해당 현장·사건·작업 화면이 소유한다.
 */
export function selectHomeAttentionSources(
  input: {
    events: readonly EventSummaryResponse[];
    workOrders: readonly ObservationWorkOrderView[];
    sites: readonly SiteView[];
    operationsByWorkOrderId?: HomeWorkOrderOperationOptions["operationsByWorkOrderId"];
    /** Core 순서(검토 대기 우선, 오래 기다린 순)를 그대로 쓴다 — AX-4. */
    externalDecisions?: readonly ExternalPendingDecision[];
  },
  limit = 3,
): HomeAttentionSource[] {
  const candidates: HomeAttentionSource[] = [
    ...sortForTriage(input.events.filter(isUnattended)).map((event) => ({
      kind: "EVENT" as const,
      key: `event:${event.eventKey}`,
      siteId: event.siteId,
      observedAt: event.occurredAt,
      event,
    })),
    ...(input.externalDecisions ?? []).map((decision) => ({
      kind: "EXTERNAL_DECISION" as const,
      key: `external-decision:${decision.reportRef}`,
      siteId: decision.siteId,
      observedAt: decision.reportedAt,
      decision,
    })),
    ...selectHomeDecisionWorkOrders(input.workOrders, input.workOrders.length, {
      operationsByWorkOrderId: input.operationsByWorkOrderId,
    }).map((workOrder) => ({
      kind: "WORK_ORDER" as const,
      key: `work-order:${workOrder.workOrderId}`,
      siteId: workOrder.siteId,
      observedAt: workOrder.updatedAt,
      workOrder,
    })),
    ...input.sites
      .filter((site) => ["UNMAPPED", "REMAP_REQUIRED", "MODEL_STALE"].includes(site.status))
      .toSorted((a, b) => a.updatedAt.localeCompare(b.updatedAt))
      .map((site) => ({
        kind: "SITE" as const,
        key: `site:${site.siteId}`,
        siteId: site.siteId,
        observedAt: site.updatedAt,
        site,
      })),
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

export type HomeRecentUpdateSource =
  | {
      kind: "RESULT_READY";
      key: string;
      siteId: string;
      observedAt: string;
      workOrder: ObservationWorkOrderView;
    }
  | {
      kind: "OBSERVATION_COMPLETED";
      key: string;
      siteId: string;
      observedAt: string;
      workOrder: ObservationWorkOrderView;
    }
  | {
      kind: "EVENT_SETTLED";
      key: string;
      siteId: string;
      observedAt: string;
      event: EventSummaryResponse;
    }
  | {
      kind: "CURRENT_LEDGER_CLEAR";
      key: string;
      siteId: string;
      observedAt: string;
      site: SiteView;
    }
  | {
      kind: "EXTERNAL_RESULT_BRIEFED";
      key: string;
      siteId: string;
      observedAt: string;
      briefing: SiteBriefing;
    };

/** Deterministic briefings recorded from external relative-volume results (AX-2). */
export function isExternalResultBriefing(briefing: SiteBriefing): boolean {
  return briefing.status === "READY" && briefing.sourceWatermark.startsWith("external-report:");
}

/**
 * Home 하단은 장비 연결·동기화·처리 시작 같은 기술 로그가 아니라 사용자가 이해할
 * 수 있는 결과·종료된 안건·현재 원장 상태만 업데이트로 보여 준다. 현장 전체의
 * 정상·안전을 추론하지 않으며, attention 영역과 같은 현장도 반복하지 않는다.
 */
export function selectHomeRecentUpdates(
  input: {
    events: readonly EventSummaryResponse[];
    workOrders: readonly ObservationWorkOrderView[];
    sites: readonly SiteView[];
    briefings?: readonly SiteBriefing[];
    excludedSiteIds?: ReadonlySet<string>;
  },
  limit = 2,
): HomeRecentUpdateSource[] {
  const excluded = input.excludedSiteIds ?? new Set<string>();
  const candidates: HomeRecentUpdateSource[] = [
    ...(input.briefings ?? [])
      .filter(isExternalResultBriefing)
      .map((briefing) => ({
        kind: "EXTERNAL_RESULT_BRIEFED" as const,
        key: `briefing:${briefing.briefingId}`,
        siteId: briefing.siteId,
        observedAt: briefing.generatedAt,
        briefing,
      })),
    ...input.workOrders
      .filter((workOrder) => workOrder.status === "REVIEW_READY" || workOrder.status === "COMPLETED")
      .map((workOrder) => ({
        kind: workOrder.status === "REVIEW_READY" ? ("RESULT_READY" as const) : ("OBSERVATION_COMPLETED" as const),
        key: `work-order:${workOrder.workOrderId}`,
        siteId: workOrder.siteId,
        observedAt: workOrder.updatedAt,
        workOrder,
      })),
    ...input.events
      .filter(isSettled)
      .map((event) => ({
        kind: "EVENT_SETTLED" as const,
        key: `event:${event.eventKey}`,
        siteId: event.siteId,
        observedAt: event.receivedAt,
        event,
      })),
  ].toSorted((a, b) => {
    const byTime = b.observedAt.localeCompare(a.observedAt);
    return byTime !== 0 ? byTime : a.key.localeCompare(b.key);
  });

  const selected: HomeRecentUpdateSource[] = [];
  const selectedSites = new Set<string>(excluded);
  for (const candidate of candidates) {
    if (selectedSites.has(candidate.siteId)) continue;
    selected.push(candidate);
    selectedSites.add(candidate.siteId);
    if (selected.length >= limit) return selected;
  }

  const sitesWithoutOpenEvents = input.sites
    .filter((site) => !selectedSites.has(site.siteId))
    .filter((site) => !input.events.some((event) => event.siteId === site.siteId && !isSettled(event)))
    .toSorted((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  for (const site of sitesWithoutOpenEvents) {
    selected.push({
      kind: "CURRENT_LEDGER_CLEAR",
      key: `site:${site.siteId}`,
      siteId: site.siteId,
      observedAt: site.updatedAt,
      site,
    });
    if (selected.length >= limit) break;
  }
  return selected;
}
