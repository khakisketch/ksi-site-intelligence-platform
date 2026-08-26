import { describe, expect, it } from "vitest";

import { summarizeWorkQueue, workOrderActionLabel } from "@/app/field/work-queue";
import type {
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
  });
});
