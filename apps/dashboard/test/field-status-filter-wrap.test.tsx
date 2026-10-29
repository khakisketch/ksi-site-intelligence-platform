/** @vitest-environment jsdom */
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({
  session: vi.fn(),
  workOrders: vi.fn(),
  operations: vi.fn(),
}));

vi.mock("@/app/field/resolve-session", () => ({ resolveFieldSession: mocked.session }));
vi.mock("@/lib/core-api/observation-work-orders", () => ({
  listObservationWorkOrdersForOrganization: mocked.workOrders,
  listObservationWorkOrderOperations: mocked.operations,
}));
vi.mock("@/app/field/WorkQueueOperationsNotices", () => ({ WorkQueueOperationsNotices: () => null }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

import FieldWorkListPage from "@/app/field/page";
import type { ObservationWorkOrderView } from "@/lib/core-api/types";

function order(overrides: Partial<ObservationWorkOrderView> = {}): ObservationWorkOrderView {
  return {
    schemaVersion: "1.0",
    workOrderId: "obs-work-opaque-0001",
    organizationId: "org-1",
    siteId: "site-opaque-0001",
    purpose: "PROGRESS_QUANTITY",
    name: "동측 구역 외부 산출물 등록",
    workAreaIds: [],
    scheduleId: null,
    executionMode: "EXTERNAL_RECONSTRUCTION",
    cycleNumber: 1,
    status: "APPROVED",
    statusReason: null,
    missionIds: [],
    processingJobIds: [],
    reportRefs: [],
    version: 1,
    createdAt: "2026-10-01T00:00:00Z",
    updatedAt: "2026-10-01T00:00:00Z",
    createdBy: "operator-1",
    approvedAt: null,
    approvedBy: null,
    ...overrides,
  };
}

beforeEach(() => {
  mocked.session.mockResolvedValue({
    kind: "ready",
    principal: { kind: "OPERATOR", principalId: "operator-1", organizationId: "org-1", permissions: ["WORK_ORDERS_WRITE"] },
  });
  mocked.workOrders.mockResolvedValue([order()]);
  mocked.operations.mockResolvedValue([]);
});

afterEach(() => { cleanup(); vi.resetAllMocks(); });

describe("Field status filter strip on narrow screens", () => {
  it("wraps instead of clipping: every status stays in the same nav without a scroll-only overflow", async () => {
    render(await FieldWorkListPage({}));
    const nav = screen.getByRole("navigation", { name: "작업 요약" });
    // Mobile-first wrap; single-row scroll density returns at sm+.
    expect(nav.className).toContain("flex-wrap");
    expect(nav.className).toContain("sm:flex-nowrap");
    expect(nav.className).toContain("sm:overflow-x-auto");
    expect(nav.className.split(" ")).not.toContain("overflow-x-auto");
    // All five filters remain links in one nav with live counts — nothing
    // hidden behind an undiscoverable swipe.
    const summary = within(nav);
    expect(summary.getByRole("link", { name: "전체 1" })).toBeTruthy();
    expect(summary.getByRole("link", { name: "결정 필요 0" })).toBeTruthy();
    expect(summary.getByRole("link", { name: "진행 중 0" })).toBeTruthy();
    expect(summary.getByRole("link", { name: "운영 상태 확인 필요 1" })).toBeTruthy();
    expect(summary.getByRole("link", { name: "완료 0" })).toBeTruthy();
    // Counts come from the queue, not fixtures: 전체 matches the record count.
    expect(summary.getByRole("link", { name: "전체 1" }).getAttribute("href")).toBe("/field");
    expect(summary.getByRole("link", { name: "전체 1" }).getAttribute("aria-current")).toBe("page");
  });

  it("keeps group/search/site scope and aria-current when a filter is active", async () => {
    render(await FieldWorkListPage({ searchParams: Promise.resolve({ q: "동측", site: "site-opaque-0001", group: "operationsUnavailable" }) }));
    const nav = screen.getByRole("navigation", { name: "작업 요약" });
    const summary = within(nav);
    const active = summary.getByRole("link", { name: "운영 상태 확인 필요 1" });
    expect(active.getAttribute("aria-current")).toBe("page");
    expect(active.getAttribute("href")).toBe("/field?q=%EB%8F%99%EC%B8%A1&site=site-opaque-0001&group=operationsUnavailable");
    // Sibling filters keep the same search/site scope.
    expect(summary.getByRole("link", { name: /결정 필요/ }).getAttribute("href")).toBe(
      "/field?q=%EB%8F%99%EC%B8%A1&site=site-opaque-0001&group=decisionRequired",
    );
    expect(summary.getByRole("link", { name: "전체 1" }).getAttribute("href")).toBe(
      "/field?q=%EB%8F%99%EC%B8%A1&site=site-opaque-0001",
    );
  });
});
