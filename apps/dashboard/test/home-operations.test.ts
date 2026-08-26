import { describe, expect, it } from "vitest";

import {
  selectHomeAttentionSources,
  selectHomeActiveWorkOrders,
  selectHomeDecisionWorkOrders,
  selectHomeInitialSetupSites,
  selectHomeRecentSiteSources,
  selectHomeRecentUpdates,
} from "@/lib/home-operations";
import type {
  EventSummaryResponse,
  ObservationWorkOrderStatus,
  ObservationWorkOrderView,
  SiteView,
} from "@/lib/core-api/types";

function workOrder(
  status: ObservationWorkOrderStatus,
  workOrderId: string,
  updatedAt: string,
): ObservationWorkOrderView {
  return {
    schemaVersion: "1.0",
    workOrderId,
    organizationId: "org-local-pilot",
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

function site(siteId: string, status: SiteView["status"] = "PATROL_READY", updatedAt = "2026-08-22T09:00:00Z"): SiteView {
  return {
    siteId,
    name: `${siteId} 현장`,
    siteFrame: { crs: "EPSG:5186", verticalDatum: "LOCAL", unit: "meter", transformVersion: "1" },
    status,
    resumeTarget: null,
    registeredAt: "2026-08-01T00:00:00Z",
    updatedAt,
    aoi: { vertices: [] },
    dataResidency: null,
    aiEgressAllowed: false,
    modelMaxAgeDays: null,
  };
}

function event(overrides: Partial<EventSummaryResponse> & Pick<EventSummaryResponse, "eventKey" | "siteId">): EventSummaryResponse {
  return {
    eventId: overrides.eventKey,
    missionId: "mission-1",
    eventType: "CHANGE_REGION",
    status: "CANDIDATE",
    severity: "MEDIUM",
    triage: "NONE",
    assignee: null,
    evidenceCount: 0,
    edgeDeviceId: "edge-1",
    occurredAt: "2026-08-22T10:00:00Z",
    receivedAt: "2026-08-22T10:01:00Z",
    ...overrides,
  };
}

describe("Home 작업 상태 분리", () => {
  it("결정 대기는 복구·승인·재관측·결과 검토 순으로, 최신 항목을 먼저 보인다", () => {
    const selected = selectHomeDecisionWorkOrders(
      [
        workOrder("REVIEW_READY", "results", "2026-08-22T09:00:00Z"),
        workOrder("AWAITING_APPROVAL", "approval-old", "2026-08-22T08:00:00Z"),
        workOrder("BLOCKED", "blocked", "2026-08-22T07:00:00Z"),
        workOrder("AWAITING_APPROVAL", "approval-new", "2026-08-22T10:00:00Z"),
        workOrder("REOBSERVATION_PENDING", "reobservation", "2026-08-22T11:00:00Z"),
      ],
      5,
    );

    expect(selected.map((item) => item.workOrderId)).toEqual([
      "blocked",
      "approval-new",
      "approval-old",
      "reobservation",
      "results",
    ]);
  });

  it("진행 중 조사는 결정 대기·완료·취소 작업과 섞지 않는다", () => {
    const selected = selectHomeActiveWorkOrders(
      [
        workOrder("PROCESSING", "processing", "2026-08-22T08:00:00Z"),
        workOrder("AWAITING_APPROVAL", "approval", "2026-08-22T11:00:00Z"),
        workOrder("MEDIA_RECEIVING", "media", "2026-08-22T10:00:00Z"),
        workOrder("COMPLETED", "completed", "2026-08-22T12:00:00Z"),
        workOrder("CANCELLED", "cancelled", "2026-08-22T13:00:00Z"),
      ],
      3,
    );

    expect(selected.map((item) => item.workOrderId)).toEqual(["media", "processing"]);
  });

  it("목록 수를 제한해 Home이 전체 작업 원장이 되지 않게 한다", () => {
    const selected = selectHomeDecisionWorkOrders(
      [
        workOrder("BLOCKED", "one", "2026-08-22T08:00:00Z"),
        workOrder("BLOCKED", "two", "2026-08-22T09:00:00Z"),
      ],
      1,
    );

    expect(selected.map((item) => item.workOrderId)).toEqual(["two"]);
  });
});

describe("Home 현장 인텔리전스 projection", () => {
  it("초기 설정 구역은 UNMAPPED 현장만 오래 기다린 순으로 제한한다", () => {
    const selected = selectHomeInitialSetupSites([
      site("ready", "PATROL_READY", "2026-08-20T09:00:00Z"),
      site("newer", "UNMAPPED", "2026-08-22T09:00:00Z"),
      site("older", "UNMAPPED", "2026-08-21T09:00:00Z"),
      site("remap", "REMAP_REQUIRED", "2026-08-19T09:00:00Z"),
    ], 1);

    expect(selected.map((item) => item.siteId)).toEqual(["older"]);
  });

  it("안건이 없을 때 최근 현장은 운영 현장을 우선하고 최신 실제 Event를 연결한다", () => {
    const selected = selectHomeRecentSiteSources({
      events: [
        event({ eventKey: "older-event", siteId: "ready", receivedAt: "2026-08-21T10:00:00Z" }),
        event({ eventKey: "newer-event", siteId: "ready", receivedAt: "2026-08-22T10:00:00Z" }),
      ],
      sites: [
        site("setup", "UNMAPPED", "2026-08-24T09:00:00Z"),
        site("ready", "PATROL_READY", "2026-08-20T09:00:00Z"),
      ],
    });

    expect(selected.map((item) => item.siteId)).toEqual(["ready", "setup"]);
    expect(selected[0]?.latestEvent?.eventKey).toBe("newer-event");
    expect(selected[0]?.observedAt).toBe("2026-08-22T10:00:00Z");
  });

  it("사건·사람 결정 작업·현장 준비 상태 순으로 고르고 같은 현장은 한 번만 보여 준다", () => {
    const sources = selectHomeAttentionSources({
      events: [event({ eventKey: "event-a", siteId: "site-a" })],
      workOrders: [
        { ...workOrder("BLOCKED", "blocked-a", "2026-08-22T11:00:00Z"), siteId: "site-a" },
        { ...workOrder("AWAITING_APPROVAL", "approval-b", "2026-08-22T12:00:00Z"), siteId: "site-b" },
        { ...workOrder("PROCESSING", "processing-c", "2026-08-22T13:00:00Z"), siteId: "site-c" },
      ],
      sites: [site("site-a"), site("site-b"), site("site-c", "UNMAPPED")],
    });

    expect(sources.map((source) => [source.kind, source.siteId])).toEqual([
      ["EVENT", "site-a"],
      ["WORK_ORDER", "site-b"],
      ["SITE", "site-c"],
    ]);
  });

  it("최근 업데이트는 결과·완료·종료 안건만 쓰고 기술 진행 상태를 넣지 않는다", () => {
    const updates = selectHomeRecentUpdates({
      events: [
        event({ eventKey: "closed", siteId: "site-c", status: "CONFIRMED_EVENT", triage: "CLOSED" }),
        event({ eventKey: "open", siteId: "site-d" }),
      ],
      workOrders: [
        { ...workOrder("REVIEW_READY", "results", "2026-08-22T14:00:00Z"), siteId: "site-a" },
        { ...workOrder("PROCESSING", "processing", "2026-08-22T15:00:00Z"), siteId: "site-b" },
      ],
      sites: [site("site-a"), site("site-b"), site("site-c"), site("site-d")],
    }, 4);

    expect(updates.map((update) => update.kind)).toEqual([
      "RESULT_READY",
      "EVENT_SETTLED",
      "CURRENT_LEDGER_CLEAR",
    ]);
    expect(updates.some((update) => update.siteId === "site-d")).toBe(false);
  });

  it("확인 필요 영역의 현장은 최근 업데이트에서 반복하지 않는다", () => {
    const updates = selectHomeRecentUpdates({
      events: [],
      workOrders: [{ ...workOrder("COMPLETED", "done", "2026-08-22T14:00:00Z"), siteId: "site-a" }],
      sites: [site("site-a"), site("site-b")],
      excludedSiteIds: new Set(["site-a"]),
    });

    expect(updates.map((update) => update.siteId)).toEqual(["site-b"]);
    expect(updates[0].kind).toBe("CURRENT_LEDGER_CLEAR");
  });
});
