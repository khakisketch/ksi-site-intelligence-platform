import { describe, expect, it } from "vitest";

import { summarizeWorkQueue } from "@/app/field/work-queue";
import { seoulDateTimeLocalValue } from "@/app/field/WorkOrderOperationsPanel";
import type { ObservationWorkOrderOperationsView, ObservationWorkOrderView } from "@/lib/core-api/types";
import { seoulDateTimeLocalToUtc } from "@/lib/external-reconstruction-submission";

const externalWorkOrder = (): ObservationWorkOrderView => ({
  schemaVersion: "1.0",
  workOrderId: "external-1",
  organizationId: "org-1",
  siteId: "site-1",
  purpose: "PROGRESS_QUANTITY",
  name: "외부 관측",
  workAreaIds: ["area-1"],
  scheduleId: null,
  executionMode: "EXTERNAL_RECONSTRUCTION",
  cycleNumber: 1,
  status: "PROCESSING",
  statusReason: null,
  missionIds: [],
  processingJobIds: [],
  reportRefs: [],
  version: 1,
  createdAt: "2026-09-10T00:00:00Z",
  updatedAt: "2026-09-10T00:00:00Z",
  createdBy: "operator-1",
  approvedAt: null,
  approvedBy: null,
});

const operations = (workflowStatus: ObservationWorkOrderOperationsView["workflowStatus"]): ObservationWorkOrderOperationsView => ({
  schemaVersion: "1.0",
  organizationId: "org-1",
  siteId: "site-1",
  workOrderId: "external-1",
  operationsRevision: workflowStatus === "UNSPECIFIED" ? 0 : 1,
  workflowStatus,
  assigneePrincipalId: null,
  dueAt: null,
  closedAt: workflowStatus === "CLOSED" ? "2026-09-10T01:00:00Z" : null,
  closedBy: workflowStatus === "CLOSED" ? "operator-1" : null,
  closeNote: null,
  updatedAt: "2026-09-10T00:00:00Z",
  updatedBy: "operator-1",
});

describe("external work operations presentation", () => {
  it("moves a closed external work order to completed and never treats unavailable operations as active", () => {
    const workOrder = externalWorkOrder();
    expect(summarizeWorkQueue([workOrder], new Map([[workOrder.workOrderId, operations("CLOSED")]])).completed).toEqual([workOrder]);
    expect(summarizeWorkQueue([workOrder], new Map()).inFlight).toEqual([]);
    expect(summarizeWorkQueue([workOrder], new Map()).operationsUnavailable).toEqual([workOrder]);
  });

  it("round-trips the explicitly labelled Seoul deadline without the browser host timezone", () => {
    expect(seoulDateTimeLocalValue("2026-09-10T00:15:00Z")).toBe("2026-09-10T09:15");
    expect(seoulDateTimeLocalToUtc(seoulDateTimeLocalValue("2026-09-10T00:15:00Z"))).toBe("2026-09-10T00:15:00Z");
  });
});
