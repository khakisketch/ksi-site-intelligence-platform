import { describe, expect, it } from "vitest";

import {
  resolveOperatorNextAction,
  resolveSiteOperatorNextAction,
} from "@/lib/operator-next-action";
import type {
  EventSummaryResponse,
  ObservationWorkOrderStatus,
  ObservationWorkOrderView,
  Permission,
  SiteStatus,
  SiteView,
} from "@/lib/core-api/types";

const OPERATOR_PERMISSIONS: Permission[] = [
  "SITES_READ",
  "SITES_WRITE",
  "MISSIONS_READ",
  "MISSIONS_ISSUE",
  "EVENTS_READ",
  "EVENTS_TRIAGE",
  "WORK_ORDERS_WRITE",
  "REOBSERVATION_APPROVE",
];

function site(
  status: SiteStatus = "UNMAPPED",
  { aoi = null, siteId = "site-1" }: { aoi?: SiteView["aoi"]; siteId?: string } = {},
): SiteView {
  return {
    siteId,
    name: siteId,
    siteFrame: {
      crs: "EPSG:5186",
      verticalDatum: "KNGeoid2018",
      unit: "meter",
      transformVersion: "v1",
    },
    status,
    resumeTarget: null,
    registeredAt: "2026-08-20T00:00:00Z",
    updatedAt: "2026-08-20T00:00:00Z",
    aoi,
    dataResidency: null,
    aiEgressAllowed: false,
    modelMaxAgeDays: null,
  };
}

function workOrder(
  status: ObservationWorkOrderStatus,
  workOrderId = `work-${status.toLowerCase()}`,
  updatedAt = "2026-08-20T00:00:00Z",
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
    createdAt: "2026-08-20T00:00:00Z",
    updatedAt,
    createdBy: "operator-1",
    approvedAt: null,
    approvedBy: null,
  };
}

function event(eventKey = "event-1", occurredAt = "2026-08-20T00:00:00Z"): EventSummaryResponse {
  return {
    eventKey,
    eventId: eventKey,
    siteId: "site-1",
    missionId: "mission-1",
    eventType: "capture_quality",
    status: "OBSERVATION",
    severity: "HIGH",
    triage: "NONE",
    assignee: null,
    evidenceCount: 0,
    edgeDeviceId: "edge-1",
    occurredAt,
    receivedAt: occurredAt,
  };
}

function resolve({
  events = [],
  workOrders = [],
  sites = [site()],
  permissions = OPERATOR_PERMISSIONS,
}: {
  events?: EventSummaryResponse[];
  workOrders?: ObservationWorkOrderView[];
  sites?: SiteView[];
  permissions?: Permission[];
} = {}) {
  return resolveOperatorNextAction({ events, workOrders, sites, permissions });
}

describe("운영자 다음 행동 우선순위", () => {
  it("미조치 이벤트가 작업과 현장 준비보다 앞선다", () => {
    const action = resolve({
      events: [event()],
      workOrders: [workOrder("BLOCKED")],
      sites: [site("UNMAPPED")],
    });
    expect(action).toMatchObject({
      kind: "REVIEW_EVENT",
      label: "지금 확인하기",
      href: "/events/event-1",
      responsiveAction: "EVENTS_TRIAGE",
      siteId: "site-1",
    });
  });

  it.each([
    ["BLOCKED", "RESOLVE_BLOCKED_WORK", "막힌 작업 확인"],
    ["AWAITING_APPROVAL", "APPROVE_WORK", "작업 승인"],
    ["REOBSERVATION_PENDING", "APPROVE_REOBSERVATION", "재관측 승인"],
    ["MEDIA_RECEIVING", "OPEN_ACTIVE_WORK", "작업 진행 상태"],
    ["REVIEW_READY", "REVIEW_RESULTS", "결과와 근거 보기"],
  ] as const)("%s 작업을 %s 행동으로 연결한다", (status, kind, label) => {
    expect(resolve({ workOrders: [workOrder(status)], sites: [] })).toMatchObject({
      kind,
      label,
    });
  });

  it("같은 우선순위에서는 가장 최근에 갱신된 작업을 고른다", () => {
    const action = resolve({
      workOrders: [
        workOrder("BLOCKED", "older", "2026-08-20T00:00:00Z"),
        workOrder("BLOCKED", "newer", "2026-08-21T00:00:00Z"),
      ],
    });
    expect(action?.href).toBe("/field/work-orders/newer");
  });

  it("쓰기 권한이 없으면 승인 버튼처럼 말하지 않고 읽기 행동으로 낮춘다", () => {
    const action = resolve({
      workOrders: [workOrder("AWAITING_APPROVAL")],
      permissions: ["SITES_READ", "MISSIONS_READ", "EVENTS_READ"],
    });
    expect(action).toMatchObject({
      label: "승인 대기 작업 확인",
      responsiveAction: "READ",
    });
  });
});

describe("현장 준비 다음 행동", () => {
  it("현장이 없으면 등록을 먼저 제시한다", () => {
    expect(resolve({ sites: [] })).toMatchObject({
      kind: "REGISTER_SITE",
      label: "현장 등록",
      href: "/sites/new",
      siteId: null,
    });
  });

  it("UNMAPPED 현장에 현장 범위가 없으면 편집기로 직접 연결한다", () => {
    expect(resolve()).toMatchObject({
      kind: "SET_SITE_AOI",
      label: "현장 범위 설정",
      href: "/sites/site-1#site-aoi",
      siteId: "site-1",
    });
  });

  it("현장 범위를 저장한 UNMAPPED 현장은 조사 계획으로 연결한다", () => {
    expect(
      resolve({ sites: [site("UNMAPPED", { aoi: { vertices: [] } })] }),
    ).toMatchObject({
      kind: "PLAN_BASELINE",
      label: "베이스라인 조사 계획하기",
      href: "/sites/site-1/surveys/new",
    });
  });

  it("REMAP_REQUIRED 현장은 기존 현장 범위가 있을 때만 재조사 계획을 제시한다", () => {
    expect(
      resolve({ sites: [site("REMAP_REQUIRED", { aoi: { vertices: [] } })] }),
    ).toMatchObject({ kind: "PLAN_REOBSERVATION", label: "재조사 계획하기" });
    expect(resolve({ sites: [site("REMAP_REQUIRED")] })).toBeNull();
  });

  it("권한이 없는 쓰기 행동은 만들지 않는다", () => {
    expect(
      resolveSiteOperatorNextAction(site(), {
        canRegisterSite: false,
        canEditSite: false,
        canIssueMission: false,
      }),
    ).toBeNull();
    expect(resolve({ sites: [], permissions: ["SITES_READ"] })).toBeNull();
  });

  it("현장 상세·목록은 준비 상태가 아닌 현장에도 명시적으로 요청할 때만 새 조사를 제공한다", () => {
    const ready = site("PATROL_READY", { aoi: { vertices: [] } });
    const permissions = {
      canRegisterSite: false,
      canEditSite: true,
      canIssueMission: true,
    };
    expect(resolveSiteOperatorNextAction(ready, permissions)).toBeNull();
    expect(
      resolveSiteOperatorNextAction(ready, permissions, { includeRoutineSurvey: true }),
    ).toMatchObject({ kind: "PLAN_SURVEY", label: "새 조사 계획하기" });
  });
});
