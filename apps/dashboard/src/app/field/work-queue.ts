import type {
  ObservationWorkOrderExecutionMode,
  ObservationWorkOrderOperationsView,
  ObservationWorkOrderView,
} from "@/lib/core-api/types";

const DECISION_STATUSES = new Set<ObservationWorkOrderView["status"]>([
  "DRAFT",
  "AWAITING_APPROVAL",
  "REVIEW_READY",
  "REOBSERVATION_PENDING",
  "BLOCKED",
]);
const ACTIVE_STATUSES = new Set<ObservationWorkOrderView["status"]>([
  "APPROVED",
  "DISPATCHED",
  "START_REPORTED",
  "MEDIA_RECEIVING",
  "PROCESSING",
]);
const COMPLETED_STATUSES = new Set<ObservationWorkOrderView["status"]>([
  "COMPLETED",
  "CANCELLED",
]);

function newestFirst(
  workOrders: readonly ObservationWorkOrderView[],
): ObservationWorkOrderView[] {
  return [...workOrders].sort(
    (left, right) =>
      right.updatedAt.localeCompare(left.updatedAt) ||
      left.workOrderId.localeCompare(right.workOrderId),
  );
}

export type WorkQueueOperationalNotice = {
  workOrder: ObservationWorkOrderView;
  operations: ObservationWorkOrderOperationsView;
  overdue: boolean;
  dueSoon: boolean;
  assignedToMe: boolean;
};

/**
 * In-app notices are a read projection, not a durable notification channel.
 * The caller supplies one render clock so adjacent labels cannot disagree at a
 * deadline boundary. Only explicit OPEN operations can produce a notice:
 * UNSPECIFIED is unknown and CLOSED is administrative history.
 */
export function deriveWorkQueueOperationalNotices(
  workOrders: readonly ObservationWorkOrderView[],
  operationsByWorkOrderId: ReadonlyMap<string, ObservationWorkOrderOperationsView>,
  principalId: string,
  now: Date,
): WorkQueueOperationalNotice[] {
  const nowMs = now.getTime();
  if (Number.isNaN(nowMs)) return [];
  const dueSoonWindowMs = 24 * 60 * 60 * 1000;
  return newestFirst(workOrders).flatMap((workOrder) => {
    const operations = operationsByWorkOrderId.get(workOrder.workOrderId);
    if (!operations || operations.workflowStatus !== "OPEN") return [];
    const dueMs = operations.dueAt === null ? Number.NaN : new Date(operations.dueAt).getTime();
    const overdue = !Number.isNaN(dueMs) && dueMs < nowMs;
    const dueSoon = !Number.isNaN(dueMs) && !overdue && dueMs - nowMs <= dueSoonWindowMs;
    const assignedToMe = operations.assigneePrincipalId === principalId;
    return overdue || dueSoon || assignedToMe
      ? [{ workOrder, operations, overdue, dueSoon, assignedToMe }]
      : [];
  });
}

export function summarizeWorkQueue(
  workOrders: readonly ObservationWorkOrderView[],
  operationsByWorkOrderId: ReadonlyMap<string, ObservationWorkOrderOperationsView> = new Map(),
) {
  const sorted = newestFirst(workOrders);
  const operationsFor = (workOrder: ObservationWorkOrderView) =>
    operationsByWorkOrderId.get(workOrder.workOrderId);
  const isClosed = (workOrder: ObservationWorkOrderView) =>
    operationsFor(workOrder)?.workflowStatus === "CLOSED";
  const isExplicitExternal = (workOrder: ObservationWorkOrderView) =>
    workOrder.executionMode === "EXTERNAL_RECONSTRUCTION";
  const isOpenExternal = (workOrder: ObservationWorkOrderView) =>
    !isExplicitExternal(workOrder) || operationsFor(workOrder)?.workflowStatus === "OPEN";
  return {
    // Administrative closure is authoritative for every external WorkOrder,
    // including legacy successors with a nullable execution mode.
    decisionRequired: sorted.filter((workOrder) => !isClosed(workOrder)
      && isOpenExternal(workOrder) && DECISION_STATUSES.has(workOrder.status)),
    inFlight: sorted.filter((workOrder) => !isClosed(workOrder)
      && isOpenExternal(workOrder) && ACTIVE_STATUSES.has(workOrder.status)),
    completed: sorted.filter((workOrder) => (
      COMPLETED_STATUSES.has(workOrder.status)
      || isClosed(workOrder)
    )),
    operationsUnavailable: sorted.filter((workOrder) => (
      isExplicitExternal(workOrder)
      && !COMPLETED_STATUSES.has(workOrder.status)
      && !isClosed(workOrder)
      && operationsFor(workOrder)?.workflowStatus !== "OPEN"
    )),
  };
}

export function workOrderActionLabel(
  status: ObservationWorkOrderView["status"],
  executionMode: ObservationWorkOrderExecutionMode | null = null,
): string {
  if (status === "APPROVED" && executionMode === "EXTERNAL_RECONSTRUCTION") return "자료 등록·검사 확인";
  if (status === "AWAITING_APPROVAL" || status === "DRAFT") return "작업 범위 검토";
  if (status === "REOBSERVATION_PENDING") return "재관측 제안 검토";
  if (status === "REVIEW_READY") return "결과와 근거 검토";
  if (status === "BLOCKED") return "막힌 이유 확인";
  if (status === "COMPLETED" || status === "CANCELLED") return "이력 보기";
  return "진행 상태 보기";
}
