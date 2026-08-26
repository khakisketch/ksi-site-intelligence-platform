import type { ObservationWorkOrderView } from "@/lib/core-api/types";

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

export function summarizeWorkQueue(workOrders: readonly ObservationWorkOrderView[]) {
  const sorted = newestFirst(workOrders);
  return {
    decisionRequired: sorted.filter((workOrder) => DECISION_STATUSES.has(workOrder.status)),
    inFlight: sorted.filter((workOrder) => ACTIVE_STATUSES.has(workOrder.status)),
    completed: sorted.filter((workOrder) => COMPLETED_STATUSES.has(workOrder.status)),
  };
}

export function workOrderActionLabel(status: ObservationWorkOrderView["status"]): string {
  if (status === "AWAITING_APPROVAL" || status === "DRAFT") return "작업 범위 검토";
  if (status === "REOBSERVATION_PENDING") return "재관측 제안 검토";
  if (status === "REVIEW_READY") return "결과와 근거 검토";
  if (status === "BLOCKED") return "막힌 이유 확인";
  if (status === "COMPLETED" || status === "CANCELLED") return "이력 보기";
  return "진행 상태 보기";
}
