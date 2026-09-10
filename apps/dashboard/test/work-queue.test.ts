import { describe, expect, it } from "vitest";

import { deriveWorkQueueOperationalNotices, summarizeWorkQueue, workOrderActionLabel } from "@/app/field/work-queue";
import type {
  ObservationWorkOrderOperationsView,
  ObservationWorkOrderStatus,
  ObservationWorkOrderView,
} from "@/lib/core-api/types";

function workOrder(
  status: ObservationWorkOrderStatus,
  workOrderId: string,
  updatedAt: string,
): ObservationWorkOrderView {
  return {
    schemaVersion: "1.0",
    workOrderId,
    organizationId: "org-1",
    siteId: "site-1",
    purpose: "PROGRESS_QUANTITY",
    name: workOrderId,
    workAreaIds: [],
    scheduleId: null,
    executionMode: null,
    cycleNumber: 1,
    status,
    statusReason: null,
    missionIds: [],
    processingJobIds: [],
    reportRefs: [],
    version: 1,
    createdAt: updatedAt,
    updatedAt,
    createdBy: "operator-1",
    approvedAt: null,
    approvedBy: null,
  };
}

describe("Operations Console 작업 큐", () => {
  it("결정·진행·완료를 분리하고 각 그룹을 최신 갱신순으로 정렬한다", () => {
    const summary = summarizeWorkQueue([
      workOrder("PROCESSING", "active-old", "2026-08-23T01:00:00Z"),
      workOrder("AWAITING_APPROVAL", "decision-old", "2026-08-23T02:00:00Z"),
      workOrder("COMPLETED", "done", "2026-08-23T03:00:00Z"),
      workOrder("BLOCKED", "decision-new", "2026-08-23T04:00:00Z"),
      workOrder("MEDIA_RECEIVING", "active-new", "2026-08-23T05:00:00Z"),
    ]);

    expect(summary.decisionRequired.map((item) => item.workOrderId)).toEqual([
      "decision-new",
      "decision-old",
    ]);
    expect(summary.inFlight.map((item) => item.workOrderId)).toEqual([
      "active-new",
      "active-old",
    ]);
    expect(summary.completed.map((item) => item.workOrderId)).toEqual(["done"]);
  });

  it("사용자에게 내부 상태값 대신 필요한 행동을 알려 준다", () => {
    expect(workOrderActionLabel("REVIEW_READY")).toBe("결과와 근거 검토");
    expect(workOrderActionLabel("REOBSERVATION_PENDING")).toBe("재관측 제안 검토");
    expect(workOrderActionLabel("PROCESSING")).toBe("진행 상태 보기");
    expect(workOrderActionLabel("APPROVED", "EXTERNAL_RECONSTRUCTION")).toBe("산출물 등록 준비");
    expect(workOrderActionLabel("APPROVED", null)).toBe("진행 상태 보기");
  });

  it("종료된 nullable legacy 외부 작업은 완료에만 두고, 확인할 수 없는 외부 작업도 열 수 있게 남긴다", () => {
    const legacy = workOrder("APPROVED", "legacy-closed", "2026-08-23T05:00:00Z");
    const external = { ...workOrder("APPROVED", "external-unknown", "2026-08-23T04:00:00Z"), executionMode: "EXTERNAL_RECONSTRUCTION" as const };
    const closed: ObservationWorkOrderOperationsView = {
      schemaVersion: "1.0", organizationId: "org-1", siteId: "site-1", workOrderId: legacy.workOrderId,
      operationsRevision: 1, workflowStatus: "CLOSED", assigneePrincipalId: null, dueAt: null,
      closedAt: "2026-08-23T05:00:00Z", closedBy: "operator-1", closeNote: null,
      updatedAt: "2026-08-23T05:00:00Z", updatedBy: "operator-1",
    };

    const summary = summarizeWorkQueue([legacy, external], new Map([[legacy.workOrderId, closed]]));

    expect(summary.completed).toEqual([legacy]);
    expect(summary.decisionRequired).toEqual([]);
    expect(summary.inFlight).toEqual([]);
    expect(summary.operationsUnavailable).toEqual([external]);
  });

  it("열린 작업만 동일 시각 기준의 내 작업·마감 알림으로 남긴다", () => {
    const overdue = workOrder("APPROVED", "overdue", "2026-09-10T00:00:00Z");
    const dueSoon = workOrder("APPROVED", "due-soon", "2026-09-10T01:00:00Z");
    const mine = workOrder("APPROVED", "mine", "2026-09-10T02:00:00Z");
    const closed = workOrder("APPROVED", "closed", "2026-09-10T03:00:00Z");
    const operations = new Map<string, ObservationWorkOrderOperationsView>([
      [overdue.workOrderId, { schemaVersion: "1.0", organizationId: "org-1", siteId: "site-1", workOrderId: overdue.workOrderId, operationsRevision: 1, workflowStatus: "OPEN", assigneePrincipalId: "operator-1", dueAt: "2026-09-10T00:30:00Z", closedAt: null, closedBy: null, closeNote: null, updatedAt: overdue.updatedAt, updatedBy: "operator-1" }],
      [dueSoon.workOrderId, { schemaVersion: "1.0", organizationId: "org-1", siteId: "site-1", workOrderId: dueSoon.workOrderId, operationsRevision: 1, workflowStatus: "OPEN", assigneePrincipalId: null, dueAt: "2026-09-11T00:00:00Z", closedAt: null, closedBy: null, closeNote: null, updatedAt: dueSoon.updatedAt, updatedBy: "operator-1" }],
      [mine.workOrderId, { schemaVersion: "1.0", organizationId: "org-1", siteId: "site-1", workOrderId: mine.workOrderId, operationsRevision: 1, workflowStatus: "OPEN", assigneePrincipalId: "operator-1", dueAt: null, closedAt: null, closedBy: null, closeNote: null, updatedAt: mine.updatedAt, updatedBy: "operator-1" }],
      [closed.workOrderId, { schemaVersion: "1.0", organizationId: "org-1", siteId: "site-1", workOrderId: closed.workOrderId, operationsRevision: 1, workflowStatus: "CLOSED", assigneePrincipalId: "operator-1", dueAt: "2026-09-10T00:30:00Z", closedAt: "2026-09-10T01:00:00Z", closedBy: "operator-1", closeNote: null, updatedAt: closed.updatedAt, updatedBy: "operator-1" }],
    ]);

    expect(deriveWorkQueueOperationalNotices([overdue, dueSoon, mine, closed], operations, "operator-1", new Date("2026-09-10T01:00:00Z"))).toEqual([
      { workOrder: mine, operations: operations.get("mine"), overdue: false, dueSoon: false, assignedToMe: true },
      { workOrder: dueSoon, operations: operations.get("due-soon"), overdue: false, dueSoon: true, assignedToMe: false },
      { workOrder: overdue, operations: operations.get("overdue"), overdue: true, dueSoon: false, assignedToMe: true },
    ]);
  });
});
