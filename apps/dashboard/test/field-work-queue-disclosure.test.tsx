/** @vitest-environment jsdom */
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({
  session: vi.fn(),
  workOrders: vi.fn(),
  operations: vi.fn(),
  sites: vi.fn(),
  areas: vi.fn(),
}));

vi.mock("@/app/field/resolve-session", () => ({ resolveFieldSession: mocked.session }));
vi.mock("@/lib/core-api/observation-work-orders", () => ({
  listObservationWorkOrdersForOrganization: mocked.workOrders,
  listObservationWorkOrderOperations: mocked.operations,
}));
vi.mock("@/lib/core-api/cached", () => ({ listSitesCached: mocked.sites }));
vi.mock("@/lib/core-api/workAreas", () => ({ listWorkAreas: mocked.areas }));
vi.mock("@/app/field/WorkQueueOperationsNotices", () => ({ WorkQueueOperationsNotices: () => null }));

import FieldWorkListPage from "@/app/field/page";
import type { ObservationWorkOrderView } from "@/lib/core-api/types";

function order(overrides: Partial<ObservationWorkOrderView> = {}): ObservationWorkOrderView {
  return {
    schemaVersion: "1.0",
    workOrderId: "wo-unique-1",
    organizationId: "org-1",
    siteId: "site-1",
    purpose: "PROGRESS_QUANTITY",
    name: "고유 관측 작업",
    workAreaIds: ["area-1"],
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
  mocked.operations.mockResolvedValue([]);
  mocked.sites.mockResolvedValue([{ siteId: "site-1", name: "한강 현장" }]);
  mocked.areas.mockResolvedValue({ workAreas: [{ workAreaId: "area-1", name: "동측 구역" }] });
});

afterEach(() => { cleanup(); vi.resetAllMocks(); });

describe("Field work queue technical disclosure", () => {
  it("유일하게 식별되는 행은 펼침 없이 compact하게 둔다", async () => {
    mocked.workOrders.mockResolvedValue([
      order({ workOrderId: "wo-unique-1", name: "첫 관측", updatedAt: "2026-10-01T00:00:00Z" }),
      order({ workOrderId: "wo-unique-2", name: "다음 관측", updatedAt: "2026-10-02T00:00:00Z" }),
    ]);
    render(await FieldWorkListPage());

    const first = screen.getByRole("link", { name: /첫 관측/ });
    const second = screen.getByRole("link", { name: /다음 관측/ });
    // 주 링크·맥락에는 원시 ID가 없다.
    for (const link of [first, second]) {
      expect(link.textContent).not.toContain("wo-unique-");
      expect(link.textContent).not.toContain("site-1");
      expect(link.textContent).not.toContain("area-1");
    }
    expect(first.textContent).toContain("한강 현장 · 동측 구역 · 1회차");
    // 펼침이 없어 스캔 밀도가 유지된다.
    expect(first.closest("li")?.querySelector("details")).toBeNull();
    expect(second.closest("li")?.querySelector("details")).toBeNull();
  });

  it("이름+맥락이 겹치는 행은 양쪽 모두 펼침으로 가른다", async () => {
    mocked.workOrders.mockResolvedValue([
      order({ workOrderId: "wo-dup-1", name: "같은 관측" }),
      order({ workOrderId: "wo-dup-2", name: "같은 관측" }),
    ]);
    render(await FieldWorkListPage());

    const links = screen.getAllByRole("link", { name: /같은 관측/ });
    expect(links).toHaveLength(2);
    for (const link of links) {
      const disclosure = link.closest("li")?.querySelector("details");
      expect(disclosure?.open).toBe(false);
      expect(within(disclosure as HTMLElement).getByText("파일 정보").tagName).toBe("SUMMARY");
    }
    expect(document.body.textContent).toContain("wo-dup-1");
    expect(document.body.textContent).toContain("wo-dup-2");
  });

  it("맥락이 빠진 행은 펼침을 둔다", async () => {
    mocked.workOrders.mockResolvedValue([order({ workOrderId: "wo-missing-1", workAreaIds: ["area-gone"] })]);
    render(await FieldWorkListPage());

    const link = screen.getByRole("link", { name: /고유 관측 작업/ });
    expect(link.textContent).not.toContain("wo-missing-1");
    const disclosure = link.closest("li")?.querySelector("details");
    expect(disclosure?.textContent).toContain("wo-missing-1");
  });
});
