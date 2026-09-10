/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WorkOrderOperationsPanel } from "@/app/field/WorkOrderOperationsPanel";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock("@/components/responsive/ResponsiveActionBoundary", () => ({
  ResponsiveActionBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
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
});

describe("WorkOrderOperationsPanel uncertain operation recovery", () => {
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
});
