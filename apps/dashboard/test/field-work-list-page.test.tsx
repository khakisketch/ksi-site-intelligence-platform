/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
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

describe("Field work list page", () => {
  it("names the work queue, inbox, and observation record consistently", async () => {
    render(await FieldWorkListPage({}));
    // 보기 전환은 탭으로, 한 줄 목적만 둔다(설명벽을 주 내비로 쓰지 않는다).
    const nav = screen.getByRole("navigation", { name: "업무 보기 방식" });
    expect(nav).toBeTruthy();
    expect(screen.getByText(/조직의 관측 작업 기록입니다.*받은 업무에서 확인하세요/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "전체 관측 작업" }).getAttribute("href")).toBe("/field");
    expect(screen.getByRole("link", { name: "받은 업무" }).getAttribute("href")).toBe("/field/inbox");
  });
  it("explains an unavailable registration action only on demand, without a registration link", async () => {
    mocked.session.mockResolvedValueOnce({
      kind: "ready",
      principal: { kind: "OPERATOR", principalId: "viewer-1", organizationId: "org-1", permissions: [] },
    });
    render(await FieldWorkListPage({}));
    expect(screen.queryByRole("link", { name: "관측 자료 등록" })).toBeNull();
    expect(screen.queryByText(/현재 계정으로는 관측 자료를 등록할 수 없습니다/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /관측 자료 등록/ }));
    expect(screen.getByText(/현재 계정으로는 관측 자료를 등록할 수 없습니다/)).toBeTruthy();
    expect(mocked.operations).not.toHaveBeenCalled();
  });
  it("does not describe an unknown operations state as an inspection task", async () => {
    render(await FieldWorkListPage({}));
    const task = screen.getByRole("link", { name: /동측 구역 외부 산출물 등록/ });
    expect(task.textContent).toContain("담당·기한 상태 확인");
    expect(task.textContent).not.toContain("자료 등록·검사 확인");
    expect(screen.getByRole("link", { name: /운영 상태 확인 필요/ })).toBeTruthy();
    expect(task.textContent).toContain("확인 불가");
  });

  it("lets a closed operation lead to history even when its retained observation is approved", async () => {
    mocked.operations.mockResolvedValueOnce([{ workOrderId: "obs-work-opaque-0001", workflowStatus: "CLOSED" }]);
    render(await FieldWorkListPage({}));
    expect(screen.getByRole("link", { name: /동측 구역 외부 산출물 등록/ }).textContent).toContain("이력 보기");
  });

  it("summarizes all four queue groups and keeps opaque IDs out of task rows", async () => {
    render(await FieldWorkListPage({}));

    const summary = within(screen.getByRole("navigation", { name: "작업 요약" }));
    expect(summary.getByText("결정 필요")).toBeTruthy();
    expect(summary.getByText("진행 중")).toBeTruthy();
    expect(summary.getByText("운영 상태 확인 필요")).toBeTruthy();
    expect(summary.getByText("완료")).toBeTruthy();
    expect(summary.getByRole("link", { name: "운영 상태 확인 필요 1" }).getAttribute("href")).toBe("/field?group=operationsUnavailable");

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

  it("filters existing records by query and state without replacing the unknown operations state", async () => {
    mocked.workOrders.mockResolvedValueOnce([order(), order({ workOrderId: "obs-2", name: "서측 등록" })]);
    render(await FieldWorkListPage({ searchParams: Promise.resolve({ q: "동측", group: "operationsUnavailable" }) }));
    expect(screen.getByRole("link", { name: /동측 구역 외부 산출물 등록/ })).toBeTruthy();
    expect(screen.queryByRole("link", { name: /서측 등록/ })).toBeNull();
    expect(screen.getByRole("link", { name: /결정 필요/ }).getAttribute("href")).toBe("/field?q=%EB%8F%99%EC%B8%A1&group=decisionRequired");
    expect(screen.queryByText("이 구분에 표시할 작업이 없습니다.")).toBeNull();
  });

  it("distinguishes a filtered empty list and accepts repeated URL parameters without crashing", async () => {
    render(await FieldWorkListPage({ searchParams: Promise.resolve({ q: "없는 작업", site: "unavailable-site" }) }));
    expect(screen.getByText("조건에 맞는 작업이 없습니다")).toBeTruthy();
    expect(screen.queryByRole("link", { name: /동측 구역 외부 산출물 등록/ })).toBeNull();
    cleanup();
    render(await FieldWorkListPage({ searchParams: Promise.resolve({ q: ["a", "b"], group: ["completed", "inFlight"] }) }));
    expect(screen.getByRole("link", { name: /동측 구역 외부 산출물 등록/ })).toBeTruthy();
  });
});
