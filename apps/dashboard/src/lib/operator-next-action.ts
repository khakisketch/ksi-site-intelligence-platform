import type { ResponsiveAction } from "@/components/responsive/responsive-actions";
import { isUnattended, sortForTriage } from "@/lib/core-api/triage";
import type {
  EventSummaryResponse,
  ObservationWorkOrderStatus,
  ObservationWorkOrderView,
  Permission,
  SiteView,
} from "@/lib/core-api/types";

export type OperatorNextActionKind =
  | "REVIEW_EVENT"
  | "RESOLVE_BLOCKED_WORK"
  | "APPROVE_WORK"
  | "APPROVE_REOBSERVATION"
  | "OPEN_ACTIVE_WORK"
  | "REVIEW_RESULTS"
  | "REGISTER_SITE"
  | "SET_SITE_AOI"
  | "PLAN_BASELINE"
  | "PLAN_REOBSERVATION"
  | "PLAN_SURVEY";

export interface OperatorNextAction {
  kind: OperatorNextActionKind;
  label: string;
  href: string;
  responsiveAction: ResponsiveAction;
  /** CTA가 어느 현장에 관한 것인지 화면에서 기술 ID 없이 설명하기 위한 문맥. */
  siteId: string | null;
}

interface SiteActionPermissions {
  canRegisterSite: boolean;
  canEditSite: boolean;
  canIssueMission: boolean;
}

export interface ResolveOperatorNextActionInput {
  events: readonly EventSummaryResponse[];
  workOrders: readonly ObservationWorkOrderView[];
  sites: readonly SiteView[];
  permissions: readonly Permission[];
}

const WORK_ORDER_PRIORITY: readonly {
  statuses: ReadonlySet<ObservationWorkOrderStatus>;
  action: (
    workOrder: ObservationWorkOrderView,
    permissions: ReadonlySet<Permission>,
  ) => OperatorNextAction;
}[] = [
  {
    statuses: new Set(["BLOCKED"]),
    action: (workOrder) => workOrderAction(workOrder, "RESOLVE_BLOCKED_WORK", "막힌 작업 확인", "READ"),
  },
  {
    statuses: new Set(["DRAFT", "AWAITING_APPROVAL"]),
    action: (workOrder, permissions) =>
      workOrderAction(
        workOrder,
        "APPROVE_WORK",
        permissions.has("WORK_ORDERS_WRITE") ? "작업 승인" : "승인 대기 작업 확인",
        permissions.has("WORK_ORDERS_WRITE") ? "WORK_ORDERS_WRITE" : "READ",
      ),
  },
  {
    statuses: new Set(["REOBSERVATION_PENDING"]),
    action: (workOrder, permissions) =>
      workOrderAction(
        workOrder,
        "APPROVE_REOBSERVATION",
        permissions.has("REOBSERVATION_APPROVE") ? "재관측 승인" : "재관측 요청 확인",
        permissions.has("REOBSERVATION_APPROVE") ? "REOBSERVATION_APPROVE" : "READ",
      ),
  },
  {
    statuses: new Set([
      "APPROVED",
      "DISPATCHED",
      "START_REPORTED",
      "MEDIA_RECEIVING",
      "PROCESSING",
    ]),
    action: (workOrder) =>
      workOrderAction(workOrder, "OPEN_ACTIVE_WORK", "작업 진행 상태", "READ"),
  },
  {
    statuses: new Set(["REVIEW_READY"]),
    action: (workOrder) =>
      workOrderAction(workOrder, "REVIEW_RESULTS", "결과와 근거 보기", "ANALYSIS_REVIEW"),
  },
];

function workOrderAction(
  workOrder: ObservationWorkOrderView,
  kind: OperatorNextActionKind,
  label: string,
  responsiveAction: ResponsiveAction,
): OperatorNextAction {
  return {
    kind,
    label,
    href: `/field/work-orders/${encodeURIComponent(workOrder.workOrderId)}`,
    responsiveAction,
    siteId: workOrder.siteId,
  };
}

function latestMatchingWorkOrder(
  workOrders: readonly ObservationWorkOrderView[],
  statuses: ReadonlySet<ObservationWorkOrderStatus>,
): ObservationWorkOrderView | null {
  return (
    workOrders
      .filter((workOrder) => statuses.has(workOrder.status))
      .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))[0] ?? null
  );
}

function sitePermissions(permissions: ReadonlySet<Permission>): SiteActionPermissions {
  return {
    canRegisterSite: permissions.has("SITES_WRITE") && permissions.has("MISSIONS_ISSUE"),
    canEditSite: permissions.has("SITES_WRITE"),
    canIssueMission: permissions.has("MISSIONS_ISSUE"),
  };
}

export function resolveSiteOperatorNextAction(
  site: SiteView,
  permissions: SiteActionPermissions,
  { includeRoutineSurvey = false }: { includeRoutineSurvey?: boolean } = {},
): OperatorNextAction | null {
  const siteHref = `/sites/${encodeURIComponent(site.siteId)}`;

  if (site.status === "UNMAPPED" && site.aoi === null) {
    if (!permissions.canEditSite) return null;
    return {
      kind: "SET_SITE_AOI",
      label: "현장 범위 설정",
      href: `${siteHref}#site-aoi`,
      responsiveAction: "SITE_DEVICE_TRANSITION",
      siteId: site.siteId,
    };
  }

  if (site.aoi !== null && site.status === "UNMAPPED") {
    if (!permissions.canIssueMission) return null;
    return {
      kind: "PLAN_BASELINE",
      label: "베이스라인 조사 계획하기",
      href: `${siteHref}/surveys/new`,
      responsiveAction: "MISSIONS_ISSUE",
      siteId: site.siteId,
    };
  }

  if (
    site.aoi !== null &&
    (site.status === "REMAP_REQUIRED" || site.status === "MODEL_STALE")
  ) {
    if (!permissions.canIssueMission) return null;
    return {
      kind: "PLAN_REOBSERVATION",
      label: "재조사 계획하기",
      href: `${siteHref}/surveys/new`,
      responsiveAction: "MISSIONS_ISSUE",
      siteId: site.siteId,
    };
  }

  if (includeRoutineSurvey && permissions.canIssueMission && site.aoi !== null) {
    return {
      kind: "PLAN_SURVEY",
      label: "새 조사 계획하기",
      href: `${siteHref}/surveys/new`,
      responsiveAction: "MISSIONS_ISSUE",
      siteId: site.siteId,
    };
  }

  // REMAP_REQUIRED인데 AOI가 없는 legacy/손상 상태는 Core가 AOI 수정을 허용하는
  // UNMAPPED가 아니다. 그 상태에서 설정 링크를 꾸며 내지 않고 현장 복구 판단에 맡긴다.
  return null;
}

export function resolveOperatorNextAction({
  events,
  workOrders,
  sites,
  permissions,
}: ResolveOperatorNextActionInput): OperatorNextAction | null {
  const permissionSet = new Set(permissions);
  const topEvent = sortForTriage(events.filter(isUnattended))[0] ?? null;
  if (topEvent) {
    return {
      kind: "REVIEW_EVENT",
      label: "지금 확인하기",
      href: `/events/${encodeURIComponent(topEvent.eventKey)}`,
      responsiveAction: "EVENTS_TRIAGE",
      siteId: topEvent.siteId,
    };
  }

  for (const candidate of WORK_ORDER_PRIORITY) {
    const workOrder = latestMatchingWorkOrder(workOrders, candidate.statuses);
    if (workOrder) return candidate.action(workOrder, permissionSet);
  }

  const permissionsForSite = sitePermissions(permissionSet);
  if (sites.length === 0) {
    if (!permissionsForSite.canRegisterSite) return null;
    return {
      kind: "REGISTER_SITE",
      label: "현장 등록",
      href: "/sites/new",
      responsiveAction: "SITE_DEVICE_TRANSITION",
      siteId: null,
    };
  }

  const attentionSites = sites
    .filter((site) => ["UNMAPPED", "REMAP_REQUIRED", "MODEL_STALE"].includes(site.status))
    .sort((a, b) => a.registeredAt.localeCompare(b.registeredAt));
  for (const site of attentionSites) {
    const action = resolveSiteOperatorNextAction(site, permissionsForSite);
    if (action) return action;
  }

  return null;
}
