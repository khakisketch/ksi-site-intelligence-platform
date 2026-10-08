import { describe, expect, it } from "vitest";

import {
  selectHomeActiveWorkOrders,
  selectHomeDecisionWorkOrders,
  selectHomeInitialSetupSites,
  selectHomeRecentSiteSources,
} from "@/lib/home-operations";
import type { ObservationWorkOrderStatus, ObservationWorkOrderView, SiteView } from "@/lib/core-api/types";

function workOrder(status: ObservationWorkOrderStatus, workOrderId: string, updatedAt: string): ObservationWorkOrderView {
  return {
    schemaVersion: "1.0", workOrderId, organizationId: "org-local", siteId: "site-1", purpose: "PROGRESS_QUANTITY",
    name: workOrderId, workAreaIds: [], scheduleId: null, executionMode: null, cycleNumber: 1, status, statusReason: null,
    missionIds: [], processingJobIds: [], reportRefs: [], version: 1, createdAt: updatedAt, updatedAt, createdBy: "operator",
    approvedAt: null, approvedBy: null,
  };
}

function site(siteId: string, status: SiteView["status"] = "PATROL_READY", updatedAt = "2026-08-22T09:00:00Z"): SiteView {
  return { siteId, name: siteId, siteFrame: { crs: "EPSG:5186", verticalDatum: "LOCAL", unit: "meter", transformVersion: "1" }, status, resumeTarget: null, registeredAt: "2026-08-01T00:00:00Z", updatedAt, aoi: null, dataResidency: null, aiEgressAllowed: false, modelMaxAgeDays: null };
}

describe("Home platform selectors", () => {
  it("작업 결정은 workflow 우선순위와 최신 갱신 순으로 고른다", () => {
    const selected = selectHomeDecisionWorkOrders([
      workOrder("REVIEW_READY", "results", "2026-08-22T09:00:00Z"),
      workOrder("AWAITING_APPROVAL", "approval-old", "2026-08-22T08:00:00Z"),
      workOrder("BLOCKED", "blocked", "2026-08-22T07:00:00Z"),
      workOrder("AWAITING_APPROVAL", "approval-new", "2026-08-22T10:00:00Z"),
    ], 4);
    expect(selected.map((item) => item.workOrderId)).toEqual(["blocked", "approval-new", "approval-old", "results"]);
  });

  it("진행 중 작업은 승인 대기·완료 작업과 분리한다", () => {
    const selected = selectHomeActiveWorkOrders([
      workOrder("PROCESSING", "processing", "2026-08-22T08:00:00Z"),
      workOrder("AWAITING_APPROVAL", "approval", "2026-08-22T11:00:00Z"),
      workOrder("COMPLETED", "completed", "2026-08-22T12:00:00Z"),
    ], 3);
    expect(selected.map((item) => item.workOrderId)).toEqual(["processing"]);
  });

  it("초기 설정 현장과 최근 현장은 사이트 원장만으로 고른다", () => {
    const sites = [site("ready"), site("newer", "UNMAPPED", "2026-08-22T09:00:00Z"), site("older", "UNMAPPED", "2026-08-21T09:00:00Z")];
    expect(selectHomeInitialSetupSites(sites, 1).map((item) => item.siteId)).toEqual(["older"]);
    expect(selectHomeRecentSiteSources(sites, 2).map((item) => item.siteId)).toEqual(["ready", "newer"]);
  });
});
