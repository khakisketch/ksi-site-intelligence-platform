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

describe("Field work list page", () => {
  it("summarizes all four queue groups and keeps opaque IDs out of task rows", async () => {
    render(await FieldWorkListPage());

    const summary = within(screen.getByRole("region", { name: "작업 요약" }));
    expect(summary.getByText("결정 필요")).toBeTruthy();
    expect(summary.getByText("진행 중")).toBeTruthy();
    expect(summary.getByText("운영 상태 확인 필요")).toBeTruthy();
    expect(summary.getByText("완료")).toBeTruthy();
    expect(summary.getByText("1")).toBeTruthy();

    const task = screen.getByRole("link", { name: /동측 구역 외부 산출물 등록/ });
    expect(task.getAttribute("href")).toBe("/field/work-orders/obs-work-opaque-0001");
    // Primary row text leads with human names, never raw IDs.
    expect(task.textContent).not.toContain("site-opaque-0001");
    expect(task.textContent).not.toContain("obs-work-opaque-0001");
    // Full technical values live only inside the closed keyboard disclosure.
    const disclosure = task.closest("li")?.querySelector("details");
    expect(disclosure?.open).toBe(false);
    const disclosureSummary = within(disclosure as HTMLElement).getByText("파일 정보");
    expect(disclosureSummary.tagName).toBe("SUMMARY");
    expect(disclosure?.textContent).toContain("obs-work-opaque-0001");
    expect(disclosure?.textContent).toContain("site-opaque-0001");
  });
});
