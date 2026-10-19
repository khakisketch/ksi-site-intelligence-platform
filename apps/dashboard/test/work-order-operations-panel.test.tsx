/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WorkOrderOperationsPanel } from "@/app/field/WorkOrderOperationsPanel";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock("@/components/responsive/ResponsiveActionBoundary", () => ({
  ResponsiveActionBoundary: ({ children, reason }: { children: React.ReactNode; reason?: string }) => <><p>{reason}</p>{children}</>,
}));

const notifyMock = vi.hoisted(() => vi.fn());
vi.mock("@/components/ui/ToastProvider", () => ({ useToast: () => ({ notify: notifyMock }) }));
vi.mock("@/components/ui/ConfirmDialog", () => ({
  ConfirmDialog: ({ open, title, description, confirmLabel, onConfirm, onCancel, pending }: {
    open: boolean; title: string; description?: React.ReactNode; confirmLabel: string;
    onConfirm: () => void; onCancel: () => void; pending?: boolean;
  }) => open ? (
    <div role="dialog" aria-label={title}>
      <p>{title}</p>
      <div>{description}</div>
      <button disabled={pending} onClick={onConfirm}>{confirmLabel}</button>
      <button onClick={onCancel}>취소</button>
    </div>
  ) : null,
}));

const openOperations = {
  schemaVersion: "1.0" as const,
  organizationId: "org-1",
  siteId: "site-1",
  workOrderId: "external-1",
  operationsRevision: 1,
  workflowStatus: "OPEN" as const,
  assigneePrincipalId: null,
  dueAt: null,
  closedAt: null,
  closedBy: null,
  closeNote: null,
  updatedAt: "2026-09-10T00:00:00Z",
  updatedBy: "operator-1",
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  notifyMock.mockClear();
});

describe("WorkOrderOperationsPanel uncertain operation recovery", () => {
  it("tells mobile users where to continue laptop-only operations", () => {
    vi.stubGlobal("fetch", vi.fn());
    render(<WorkOrderOperationsPanel workOrderId="external-1" principalId="operator-1" initialOperations={openOperations} canWrite />);

    expect(screen.getByText("노트북에서 같은 계정으로 이 작업 상세를 열어 담당·기한·업무 종료 변경을 이어가세요.")).toBeTruthy();
  });

  it("aligns the open status text with the operation card body inset", () => {
    vi.stubGlobal("fetch", vi.fn());
    render(<WorkOrderOperationsPanel workOrderId="external-1" principalId="operator-1" initialOperations={openOperations} canWrite />);

    const status = screen.getByText("운영 중");
    expect(status.tagName).toBe("SPAN");
    expect(status.className).toContain("pl-0");
    expect(status.className).not.toContain("px-2.5");
  });

  it("keeps roster failure distinct from an empty roster and allows a retry", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ members: [{ principalId: "operator-b", displayName: "현장 담당", roleHint: "FIELD_OPERATOR", status: "ACTIVE" }] }) });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkOrderOperationsPanel workOrderId="external-1" principalId="operator-1" initialOperations={openOperations} canWrite />);
    fireEvent.click(screen.getByRole("button", { name: "팀원에게 배정" }));
    await screen.findByRole("status");
    expect(screen.queryByText("배정 가능한 활성 팀원이 없습니다")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "팀원 목록 다시 불러오기" }));
    await screen.findByRole("option", { name: /현장 담당/ });
  });

  it("keeps the exact frozen request after a 504 and clears it after definitive 409 reconciliation", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 504, json: async () => ({ detail: "Gateway Timeout" }) })
      .mockResolvedValueOnce({ ok: false, status: 409, json: async () => ({ detail: "STALE_OPERATIONS_REVISION" }) })
      .mockResolvedValueOnce({ ok: true, json: async () => openOperations });
    vi.stubGlobal("fetch", fetchMock);

    render(<WorkOrderOperationsPanel workOrderId="external-1" principalId="operator-1" initialOperations={openOperations} canWrite />);
    fireEvent.click(screen.getByRole("button", { name: "내게 배정" }));
    await screen.findByRole("status");
    expect(screen.getByRole("status").textContent).toContain("응답을 확인하지 못했습니다");
    expect(screen.getByRole("status").textContent).not.toContain("요청은 저장되지 않았습니다");

    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(fetchMock.mock.calls[1]?.[1]?.headers["Idempotency-Key"]).toBe(fetchMock.mock.calls[0]?.[1]?.headers["Idempotency-Key"]);
    expect(fetchMock.mock.calls[1]?.[1]?.body).toBe(fetchMock.mock.calls[0]?.[1]?.body);
    await waitFor(() => expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull());
    expect(screen.getByRole("status").textContent).toContain("다른 변경이 먼저 저장되었습니다");
  });

  it("confirms an irreversible close explicitly and keeps the entered note when cancelled", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkOrderOperationsPanel workOrderId="external-1" principalId="operator-1" initialOperations={openOperations} canWrite />);

    fireEvent.change(screen.getByPlaceholderText("예: 현장 확인과 결과 검토를 마쳤습니다."), { target: { value: "마무리 메모" } });
    fireEvent.click(screen.getByRole("button", { name: "업무 종료" }));
    expect(fetchMock).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog", { name: "업무를 종료할까요?" });
    expect(within(dialog).queryByText(/되돌릴 수 없/)).toBeNull();
    expect(within(dialog).getByText(/새 산출물 등록이 멈춥니다/)).toBeTruthy();
    expect(within(dialog).getByText(/필요하면 업무를 다시 열 수 있습니다/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "취소" }));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect((screen.getByPlaceholderText("예: 현장 확인과 결과 검토를 마쳤습니다.") as HTMLTextAreaElement).value).toBe("마무리 메모");
    expect(notifyMock).not.toHaveBeenCalled();
  });

  it("posts the close exactly once after confirmation and toasts the verified save", async () => {
    const closed = { ...openOperations, workflowStatus: "CLOSED" as const, closedAt: "2026-09-11T00:00:00Z", closeNote: "마무리 메모" };
    const fetchMock = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => closed });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkOrderOperationsPanel workOrderId="external-1" principalId="operator-1" initialOperations={openOperations} canWrite />);

    fireEvent.change(screen.getByPlaceholderText("예: 현장 확인과 결과 검토를 마쳤습니다."), { target: { value: "마무리 메모" } });
    fireEvent.click(screen.getByRole("button", { name: "업무 종료" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "업무를 종료할까요?" })).getByRole("button", { name: "업무 종료" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/observation-work-orders/external-1/operations/close");
    expect(JSON.parse(fetchMock.mock.calls[0]?.[1]?.body)).toEqual({ expectedOperationsRevision: 1, note: "마무리 메모" });
    await waitFor(() => expect(notifyMock).toHaveBeenCalledWith("업무를 종료했습니다."));
  });

  it("keeps the existing reopen path without a confirmation modal", async () => {
    const closed = { ...openOperations, workflowStatus: "CLOSED" as const, closedAt: "2026-09-11T00:00:00Z", closeNote: null };
    const reopened = { ...openOperations, operationsRevision: 2 };
    const fetchMock = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => reopened });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkOrderOperationsPanel workOrderId="external-1" principalId="operator-1" initialOperations={closed} canWrite />);

    fireEvent.click(screen.getByRole("button", { name: "업무 다시 열기" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/observation-work-orders/external-1/operations/reopen");
    await waitFor(() => expect(notifyMock).toHaveBeenCalledWith("운영 정보를 저장했습니다."));
  });

  it("replaces the no-permission edit form with one on-demand blocked action", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkOrderOperationsPanel workOrderId="external-1" principalId="operator-1" initialOperations={openOperations} canWrite={false} />);

    expect(screen.getByText("작업 운영")).toBeTruthy();
    expect(screen.getByText("운영 중")).toBeTruthy();
    expect(screen.getByText("마감")).toBeTruthy();

    const blocked = screen.getByRole("button", { name: "작업 운영 정보 변경" });
    expect((blocked as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByText(/현재 계정으로는 담당·기한·업무 종료를 변경할 수 없습니다/)).toBeNull();
    fireEvent.click(blocked);
    expect(await screen.findByText(/현재 계정으로는 담당·기한·업무 종료를 변경할 수 없습니다/)).toBeTruthy();
    expect(screen.getByText(/작업 담당자에게 문의하세요/)).toBeTruthy();

    expect(screen.queryByRole("button", { name: "내게 배정" })).toBeNull();
    expect(screen.queryByRole("button", { name: "팀원에게 배정" })).toBeNull();
    expect(screen.queryByRole("button", { name: "담당 해제" })).toBeNull();
    expect(screen.queryByRole("button", { name: "마감 저장" })).toBeNull();
    expect(screen.queryByRole("button", { name: "업무 종료" })).toBeNull();
    expect(screen.queryByText("이 계정에는 작업 운영 정보를 변경할 권한이 없습니다.")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
