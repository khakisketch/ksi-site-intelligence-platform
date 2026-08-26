import { describe, expect, it } from "vitest";

import { presentWorkOrder } from "@/app/field/work-order-stage";

describe("presentWorkOrder", () => {
  it("shows one human approval action before first dispatch", () => {
    const view = presentWorkOrder("AWAITING_APPROVAL");
    expect(view).toMatchObject({ step: 1, action: "APPROVE", actionLabel: "작업 승인" });
  });

  it("does not expose file transfer as the normal approved action", () => {
    const view = presentWorkOrder("APPROVED");
    expect(view.action).toBe("REFRESH");
    expect(view.label).toBe("비행 계획 준비");
    expect(view.detail).toContain("WorkOrder 정보");
  });

  it("keeps reobservation behind a distinct human approval", () => {
    const view = presentWorkOrder("REOBSERVATION_PENDING");
    expect(view).toMatchObject({ step: 5, action: "APPROVE_REOBSERVATION" });
  });

  it("opens grounded results only when review is ready", () => {
    expect(presentWorkOrder("PROCESSING").action).toBe("REFRESH");
    expect(presentWorkOrder("REVIEW_READY").action).toBe("OPEN_RESULTS");
    expect(presentWorkOrder("COMPLETED").action).toBe("OPEN_RESULTS");
  });
});
