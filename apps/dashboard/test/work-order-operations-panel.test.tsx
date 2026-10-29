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

  it("keeps the exact frozen request after a 504 and keeps it through a retry 409 with read-only refresh", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 504, json: async () => ({ detail: "Gateway Timeout" }) })
      .mockResolvedValueOnce({ ok: false, status: 409, json: async () => ({ detail: "STALE_OPERATIONS_REVISION" }) })
      .mockResolvedValueOnce({ ok: true, json: async () => openOperations });
    vi.stubGlobal("fetch", fetchMock);

    render(<WorkOrderOperationsPanel workOrderId="external-1" principalId="operator-1" initialOperations={openOperations} canWrite accountIdentity={{ fingerprint: `v1-${"a".repeat(64)}` }} />);
    fireEvent.click(screen.getByRole("button", { name: "내게 배정" }));
    await screen.findByRole("status");
    expect(screen.getByRole("status").textContent).toContain("응답을 확인하지 못했습니다");
    expect(screen.getByRole("status").textContent).not.toContain("요청은 저장되지 않았습니다");

    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(fetchMock.mock.calls[1]?.[1]?.headers["Idempotency-Key"]).toBe(fetchMock.mock.calls[0]?.[1]?.headers["Idempotency-Key"]);
    expect(fetchMock.mock.calls[1]?.[1]?.body).toBe(fetchMock.mock.calls[0]?.[1]?.body);
    // A retry 409 only rejects the retry — the lost original may already be
    // committed — so the freeze stays with a read-only refresh, not a clear.
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).not.toBeNull();
    expect(screen.getByRole("status").textContent).toContain("이전 요청이 처리되었는지는 알 수 없습니다");

    fireEvent.click(screen.getByRole("button", { name: "동결된 요청 버리기" }));
    fireEvent.click(screen.getByRole("button", { name: "버리기 확인" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull());
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("keeps the frozen request when a same-key retry is denied and allows explicit discard", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: false, status: 401, json: async () => ({ message: "세션이 만료되었습니다." }) });
    vi.stubGlobal("fetch", fetchMock);

    render(<WorkOrderOperationsPanel workOrderId="external-1" principalId="operator-1" initialOperations={openOperations} canWrite accountIdentity={{ fingerprint: `v1-${"a".repeat(64)}` }} />);
    fireEvent.click(screen.getByRole("button", { name: "내게 배정" }));
    await screen.findByRole("status");
    expect(screen.getByRole("status").textContent).toContain("응답을 확인하지 못했습니다");

    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1]?.[1]?.headers["Idempotency-Key"]).toBe(fetchMock.mock.calls[0]?.[1]?.headers["Idempotency-Key"]);
    expect(fetchMock.mock.calls[1]?.[1]?.headers["x-ksi-continuity-fingerprint"]).toBe(fetchMock.mock.calls[0]?.[1]?.headers["x-ksi-continuity-fingerprint"]);
    expect(JSON.parse(fetchMock.mock.calls[1]?.[1]?.body)).toEqual(JSON.parse(fetchMock.mock.calls[0]?.[1]?.body));
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).not.toBeNull();
    expect(screen.getByRole("status").textContent).toContain("이전 요청이 처리되었는지는 알 수 없습니다");
    expect(screen.getByRole("status").textContent).not.toContain("요청은 저장되지 않았습니다");

    fireEvent.click(screen.getByRole("button", { name: "동결된 요청 버리기" }));
    expect(screen.getByRole("button", { name: "버리기 확인" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "취소" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(2);

    fireEvent.click(screen.getByRole("button", { name: "취소" }));
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).not.toBeNull();
    expect(screen.queryByRole("button", { name: "버리기 확인" })).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(2);

    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(fetchMock.mock.calls[2]?.[1]?.headers["Idempotency-Key"]).toBe(fetchMock.mock.calls[0]?.[1]?.headers["Idempotency-Key"]);

    fireEvent.click(screen.getByRole("button", { name: "동결된 요청 버리기" }));
    fireEvent.click(screen.getByRole("button", { name: "버리기 확인" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "버리기 확인" })).toBeNull());
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(screen.getByRole("status").textContent).toContain("버린 요청이 처리되었는지는 알 수 없");
    expect(screen.getByRole("status").textContent).toContain("새 요청으로 기록됩니다");
  });

  it("freezes an unproven first-attempt status with same-key recovery", async () => {
    const advanced = { ...openOperations, operationsRevision: 2, assigneePrincipalId: "operator-1" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 418, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, json: async () => advanced });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkOrderOperationsPanel workOrderId="external-1" principalId="operator-1" initialOperations={openOperations} canWrite accountIdentity={{ fingerprint: `v1-${"a".repeat(64)}` }} />);
    fireEvent.click(screen.getByRole("button", { name: "내게 배정" }));
    await screen.findByRole("status");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).not.toBeNull();
    expect(screen.getByRole("status").textContent).toContain("기록 여부를 확인할 수 없");
    expect(screen.getByRole("status").textContent).not.toContain("이번 요청은 기록되지 않았습니다");
    expect(notifyMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1]?.[1]?.headers["Idempotency-Key"]).toBe(fetchMock.mock.calls[0]?.[1]?.headers["Idempotency-Key"]);
    expect(JSON.parse(fetchMock.mock.calls[1]?.[1]?.body)).toEqual(JSON.parse(fetchMock.mock.calls[0]?.[1]?.body));
    expect(fetchMock.mock.calls[1]?.[0]).toContain("external-1");
    await waitFor(() => expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull());
    expect(notifyMock).toHaveBeenCalledWith("운영 정보를 저장했습니다.");
  });

  it("freezes a bare first-attempt 400 as unknown and recovers with the same key", async () => {
    const advanced = { ...openOperations, operationsRevision: 2, assigneePrincipalId: "operator-1" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 400, json: async () => ({ message: "담당 지정 요청 형식이 올바르지 않습니다." }) })
      .mockResolvedValueOnce({ ok: true, json: async () => advanced });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkOrderOperationsPanel workOrderId="external-1" principalId="operator-1" initialOperations={openOperations} canWrite accountIdentity={{ fingerprint: `v1-${"a".repeat(64)}` }} />);
    fireEvent.click(screen.getByRole("button", { name: "내게 배정" }));
    await screen.findByRole("status");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).not.toBeNull();
    expect(screen.getByRole("status").textContent).toContain("기록 여부를 확인할 수 없");
    expect(screen.getByRole("status").textContent).not.toContain("이번 요청은 기록되지 않았습니다");

    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1]?.[1]?.headers["Idempotency-Key"]).toBe(fetchMock.mock.calls[0]?.[1]?.headers["Idempotency-Key"]);
    await waitFor(() => expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull());
  });

  it("keeps the freeze on a malformed success payload and recovers with the same key", async () => {
    const advanced = { ...openOperations, operationsRevision: 2, assigneePrincipalId: "operator-1" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, json: async () => advanced });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkOrderOperationsPanel workOrderId="external-1" principalId="operator-1" initialOperations={openOperations} canWrite accountIdentity={{ fingerprint: `v1-${"a".repeat(64)}` }} />);
    fireEvent.click(screen.getByRole("button", { name: "내게 배정" }));
    await screen.findByRole("status");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).not.toBeNull();
    expect(screen.getByRole("status").textContent).toContain("기록 여부는 알 수 없습니다");
    expect(notifyMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1]?.[1]?.headers["Idempotency-Key"]).toBe(fetchMock.mock.calls[0]?.[1]?.headers["Idempotency-Key"]);
    await waitFor(() => expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull());
    expect(notifyMock).toHaveBeenCalledWith("운영 정보를 저장했습니다.");
  });

  it("keeps the freeze on a same-target response with a wrong revision", async () => {
    const stale = { ...openOperations, operationsRevision: 1, assigneePrincipalId: "operator-1" };
    const advanced = { ...openOperations, operationsRevision: 2, assigneePrincipalId: "operator-1" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, json: async () => stale })
      .mockResolvedValueOnce({ ok: true, json: async () => advanced });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkOrderOperationsPanel workOrderId="external-1" principalId="operator-1" initialOperations={openOperations} canWrite accountIdentity={{ fingerprint: `v1-${"a".repeat(64)}` }} />);
    fireEvent.click(screen.getByRole("button", { name: "내게 배정" }));
    await screen.findByRole("status");

    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).not.toBeNull();
    expect(screen.getByRole("status").textContent).toContain("기록 여부는 알 수 없습니다");
    expect(notifyMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(fetchMock.mock.calls[2]?.[1]?.headers["Idempotency-Key"]).toBe(fetchMock.mock.calls[0]?.[1]?.headers["Idempotency-Key"]);
    await waitFor(() => expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull());
    expect(notifyMock).toHaveBeenCalledWith("운영 정보를 저장했습니다.");
  });

  it("keeps the freeze on an impossible assign-to-me echo without the assignee", async () => {
    const impossible = { ...openOperations, operationsRevision: 2, assigneePrincipalId: null };
    const advanced = { ...openOperations, operationsRevision: 2, assigneePrincipalId: "operator-1" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, json: async () => impossible })
      .mockResolvedValueOnce({ ok: true, json: async () => advanced });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkOrderOperationsPanel workOrderId="external-1" principalId="operator-1" initialOperations={openOperations} canWrite accountIdentity={{ fingerprint: `v1-${"a".repeat(64)}` }} />);
    fireEvent.click(screen.getByRole("button", { name: "내게 배정" }));
    await screen.findByRole("status");

    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).not.toBeNull();
    expect(screen.getByRole("status").textContent).toContain("기록 여부는 알 수 없습니다");
    expect(notifyMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(fetchMock.mock.calls[2]?.[1]?.headers["Idempotency-Key"]).toBe(fetchMock.mock.calls[0]?.[1]?.headers["Idempotency-Key"]);
    await waitFor(() => expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull());
    expect(notifyMock).toHaveBeenCalledWith("운영 정보를 저장했습니다.");
  });

  it("keeps the freeze on an incomplete same-target payload", async () => {
    const incomplete = { schemaVersion: "1.0", workOrderId: "external-1", organizationId: "org-1", siteId: "site-1", workflowStatus: "OPEN" };
    const advanced = { ...openOperations, operationsRevision: 2, assigneePrincipalId: "operator-1" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, json: async () => incomplete })
      .mockResolvedValueOnce({ ok: true, json: async () => advanced });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkOrderOperationsPanel workOrderId="external-1" principalId="operator-1" initialOperations={openOperations} canWrite accountIdentity={{ fingerprint: `v1-${"a".repeat(64)}` }} />);
    fireEvent.click(screen.getByRole("button", { name: "내게 배정" }));
    await screen.findByRole("status");

    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).not.toBeNull();
    expect(screen.getByRole("status").textContent).toContain("기록 여부는 알 수 없습니다");
    expect(notifyMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull());
    expect(notifyMock).toHaveBeenCalledWith("운영 정보를 저장했습니다.");
  });

  it("keeps the freeze on a success echo for a different work order", async () => {
    const other = { ...openOperations, workOrderId: "external-9", operationsRevision: 2 };
    const advanced = { ...openOperations, operationsRevision: 2, assigneePrincipalId: "operator-1" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, json: async () => other })
      .mockResolvedValueOnce({ ok: true, json: async () => advanced });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkOrderOperationsPanel workOrderId="external-1" principalId="operator-1" initialOperations={openOperations} canWrite accountIdentity={{ fingerprint: `v1-${"a".repeat(64)}` }} />);
    fireEvent.click(screen.getByRole("button", { name: "내게 배정" }));
    await screen.findByRole("status");

    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).not.toBeNull();
    expect(screen.getByRole("status").textContent).toContain("기록 여부는 알 수 없습니다");
    expect(notifyMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(fetchMock.mock.calls[2]?.[1]?.headers["Idempotency-Key"]).toBe(fetchMock.mock.calls[0]?.[1]?.headers["Idempotency-Key"]);
    await waitFor(() => expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull());
    expect(notifyMock).toHaveBeenCalledWith("운영 정보를 저장했습니다.");
  });

  it("confirms the original request without regressing newer displayed state", async () => {
    const newer = { ...openOperations, operationsRevision: 3, assigneePrincipalId: "operator-x" };
    const replay = { ...openOperations, operationsRevision: 2, assigneePrincipalId: "operator-1" };
    const fingerprint = `v1-${"a".repeat(64)}`;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, json: async () => newer })
      .mockResolvedValueOnce({ ok: true, json: async () => replay });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkOrderOperationsPanel workOrderId="external-1" principalId="operator-1" initialOperations={openOperations} canWrite accountIdentity={{ fingerprint }} />);
    fireEvent.click(screen.getByRole("button", { name: "내게 배정" }));
    await screen.findByRole("status");

    fireEvent.click(screen.getByRole("button", { name: "현재 상태 다시 불러오기" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(screen.getByText(/다른 담당자에게 배정됨/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(fetchMock.mock.calls[2]?.[1]?.headers["Idempotency-Key"]).toBe(fetchMock.mock.calls[0]?.[1]?.headers["Idempotency-Key"]);
    expect(fetchMock.mock.calls[2]?.[1]?.headers["x-ksi-continuity-fingerprint"]).toBe(fingerprint);
    await waitFor(() => expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull());
    expect(screen.getByText(/다른 담당자에게 배정됨/)).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain("원래 요청이 이미 반영된 것");
    expect(notifyMock).not.toHaveBeenCalled();
  });

  it("keeps read-only recovery without retry when write permission is lost", async () => {
    const reloaded = { ...openOperations, operationsRevision: 2 };
    const replay = { ...openOperations, operationsRevision: 2, assigneePrincipalId: "operator-1" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, json: async () => reloaded })
      .mockResolvedValueOnce({ ok: true, json: async () => replay });
    vi.stubGlobal("fetch", fetchMock);
    const props = { workOrderId: "external-1", principalId: "operator-1", initialOperations: openOperations, accountIdentity: { fingerprint: `v1-${"a".repeat(64)}` } };
    const { rerender } = render(<WorkOrderOperationsPanel {...props} canWrite />);
    fireEvent.click(screen.getByRole("button", { name: "내게 배정" }));
    await screen.findByRole("status");
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).not.toBeNull();

    rerender(<WorkOrderOperationsPanel {...props} canWrite={false} />);
    expect(screen.getByText(/이미 기록됐을 수 있습니다/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull();
    expect(screen.getByRole("button", { name: "현재 상태 다시 불러오기" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "동결된 요청 버리기" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "현재 상태 다시 불러오기" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1]?.[1]?.method).toBeUndefined();
    expect(String(fetchMock.mock.calls[1]?.[0])).toContain("/operations");
    expect(String(fetchMock.mock.calls[1]?.[0])).not.toContain("assignment");
    expect(screen.getByText(/이미 기록됐을 수 있습니다/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull();

    rerender(<WorkOrderOperationsPanel {...props} canWrite />);
    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(fetchMock.mock.calls[2]?.[1]?.headers["Idempotency-Key"]).toBe(fetchMock.mock.calls[0]?.[1]?.headers["Idempotency-Key"]);
    await waitFor(() => expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull());
    expect(notifyMock).toHaveBeenCalledWith("운영 정보를 저장했습니다.");
  });

  it("binds success to the frozen actor even when the live principal prop changes", async () => {
    const replay = { ...openOperations, operationsRevision: 2, assigneePrincipalId: "operator-1" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, json: async () => replay });
    vi.stubGlobal("fetch", fetchMock);
    const { rerender } = render(<WorkOrderOperationsPanel workOrderId="external-1" principalId="operator-1" initialOperations={openOperations} canWrite accountIdentity={{ fingerprint: `v1-${"a".repeat(64)}` }} />);
    fireEvent.click(screen.getByRole("button", { name: "내게 배정" }));
    await screen.findByRole("status");

    rerender(<WorkOrderOperationsPanel workOrderId="external-1" principalId="operator-2" initialOperations={openOperations} canWrite accountIdentity={{ fingerprint: `v1-${"a".repeat(64)}` }} />);
    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull());
    expect(notifyMock).toHaveBeenCalledWith("운영 정보를 저장했습니다.");
  });

  it("keeps display and freeze when refresh returns a malformed payload", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkOrderOperationsPanel workOrderId="external-1" principalId="operator-1" initialOperations={openOperations} canWrite accountIdentity={{ fingerprint: `v1-${"a".repeat(64)}` }} />);
    fireEvent.click(screen.getByRole("button", { name: "내게 배정" }));
    await screen.findByRole("status");

    fireEvent.click(screen.getByRole("button", { name: "현재 상태 다시 불러오기" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).not.toBeNull();
    expect(screen.getByRole("status").textContent).toContain("다시 불러오지 못했습니다");
    expect(screen.getByText("미배정", { exact: false })).toBeTruthy();
  });

  it("keeps display and freeze when refresh returns a different work order", async () => {
    const other = { ...openOperations, operationsRevision: 2, workOrderId: "external-9" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, json: async () => other });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkOrderOperationsPanel workOrderId="external-1" principalId="operator-1" initialOperations={openOperations} canWrite accountIdentity={{ fingerprint: `v1-${"a".repeat(64)}` }} />);
    fireEvent.click(screen.getByRole("button", { name: "내게 배정" }));
    await screen.findByRole("status");

    fireEvent.click(screen.getByRole("button", { name: "현재 상태 다시 불러오기" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).not.toBeNull();
    expect(screen.getByRole("status").textContent).toContain("다시 불러오지 못했습니다");
  });

  it("freezes a same-target same-revision reply missing the other required fields", async () => {
    const partial = { schemaVersion: "1.0", workOrderId: "external-1", organizationId: "org-1", siteId: "site-1", operationsRevision: 2, workflowStatus: "OPEN", assigneePrincipalId: "operator-1" };
    const advanced = { ...openOperations, operationsRevision: 2, assigneePrincipalId: "operator-1" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, json: async () => partial })
      .mockResolvedValueOnce({ ok: true, json: async () => advanced });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkOrderOperationsPanel workOrderId="external-1" principalId="operator-1" initialOperations={openOperations} canWrite accountIdentity={{ fingerprint: `v1-${"a".repeat(64)}` }} />);
    fireEvent.click(screen.getByRole("button", { name: "내게 배정" }));
    await screen.findByRole("status");

    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).not.toBeNull();
    expect(screen.getByRole("status").textContent).toContain("기록 여부는 알 수 없습니다");
    expect(notifyMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(fetchMock.mock.calls[2]?.[1]?.headers["Idempotency-Key"]).toBe(fetchMock.mock.calls[0]?.[1]?.headers["Idempotency-Key"]);
    await waitFor(() => expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull());
    expect(notifyMock).toHaveBeenCalledWith("운영 정보를 저장했습니다.");
  });

  it("shows the discard consequence before any discard choice", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkOrderOperationsPanel workOrderId="external-1" principalId="operator-1" initialOperations={openOperations} canWrite accountIdentity={{ fingerprint: `v1-${"a".repeat(64)}` }} />);
    fireEvent.click(screen.getByRole("button", { name: "내게 배정" }));
    await screen.findByRole("status");
    expect(screen.getByText(/이미 기록됐을 수 있습니다/)).toBeTruthy();
    expect(screen.getByText(/새 요청\(새 키\)으로 기록됩니다/)).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("blocks a new mutation when the server-derived identity is missing or malformed", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const { unmount } = render(<WorkOrderOperationsPanel workOrderId="external-1" principalId="operator-1" initialOperations={openOperations} canWrite />);
    fireEvent.click(screen.getByRole("button", { name: "내게 배정" }));
    await screen.findByRole("status");
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByRole("status").textContent).toContain("계정을 확인하지 못해 새 변경을 시작할 수 없습니다");
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull();
    unmount();
    cleanup();

    render(<WorkOrderOperationsPanel workOrderId="external-1" principalId="operator-1" initialOperations={openOperations} canWrite accountIdentity={{ fingerprint: "not-a-fingerprint" }} />);
    fireEvent.click(screen.getByRole("button", { name: "내게 배정" }));
    await screen.findByRole("status");
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByRole("status").textContent).toContain("계정을 확인하지 못해 새 변경을 시작할 수 없습니다");
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull();
  });

  it("retries a preserved unresolved request with its original continuity when current identity is missing", async () => {
    const fingerprint = `v1-${"e".repeat(64)}`;
    const advanced = { ...openOperations, operationsRevision: 2, assigneePrincipalId: "operator-1" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, json: async () => advanced });
    vi.stubGlobal("fetch", fetchMock);
    const props = { workOrderId: "external-1", principalId: "operator-1", initialOperations: openOperations, canWrite: true as const };
    const { rerender } = render(<WorkOrderOperationsPanel {...props} accountIdentity={{ fingerprint }} />);
    fireEvent.click(screen.getByRole("button", { name: "내게 배정" }));
    await screen.findByRole("status");
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).not.toBeNull();

    rerender(<WorkOrderOperationsPanel {...props} accountIdentity={null} />);
    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1]?.[1]?.headers["x-ksi-continuity-fingerprint"]).toBe(fingerprint);
    expect(fetchMock.mock.calls[1]?.[1]?.headers["Idempotency-Key"]).toBe(fetchMock.mock.calls[0]?.[1]?.headers["Idempotency-Key"]);
    await waitFor(() => expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull());
  });

  it("refuses to redirect a frozen request to a changed work order path", async () => {
    const fingerprint = `v1-${"e".repeat(64)}`;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
    const { rerender } = render(<WorkOrderOperationsPanel workOrderId="external-1" principalId="operator-1" initialOperations={openOperations} canWrite accountIdentity={{ fingerprint }} />);
    fireEvent.click(screen.getByRole("button", { name: "내게 배정" }));
    await screen.findByRole("status");
    expect(fetchMock.mock.calls[0]?.[0]).toContain("external-1");

    rerender(<WorkOrderOperationsPanel workOrderId="external-2" principalId="operator-1" initialOperations={openOperations} canWrite accountIdentity={{ fingerprint }} />);
    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await screen.findByRole("status");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).not.toBeNull();
    expect(screen.getByRole("status").textContent).toContain("다른 작업(external-1)");
  });

  it("never claims a reload succeeded when the retry-409 refresh fails", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: false, status: 409, json: async () => ({ detail: "OPERATIONS_REVISION_CONFLICT" }) })
      .mockResolvedValueOnce({ ok: false, status: 500, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkOrderOperationsPanel workOrderId="external-1" principalId="operator-1" initialOperations={openOperations} canWrite accountIdentity={{ fingerprint: `v1-${"e".repeat(64)}` }} />);
    fireEvent.click(screen.getByRole("button", { name: "내게 배정" }));
    await screen.findByRole("status");

    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).not.toBeNull();
    expect(screen.getByRole("status").textContent).toContain("이전 요청이 처리되었는지는 알 수 없습니다");
    expect(screen.getByRole("status").textContent).not.toContain("다시 불러왔습니다");
  });

  it("keeps the freeze when the account changes between attempts", async () => {
    const fingerprint = `v1-${"b".repeat(64)}`;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: false, status: 409, json: async () => ({ code: "ACCOUNT_CONTINUITY_MISMATCH" }) });
    vi.stubGlobal("fetch", fetchMock);

    render(<WorkOrderOperationsPanel workOrderId="external-1" principalId="operator-1" initialOperations={openOperations} canWrite accountIdentity={{ fingerprint }} />);
    fireEvent.click(screen.getByRole("button", { name: "내게 배정" }));
    await screen.findByRole("status");

    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1]?.[1]?.headers["x-ksi-continuity-fingerprint"]).toBe(fingerprint);
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).not.toBeNull();
    expect(screen.getByRole("status").textContent).toContain("계정이 바뀌어");
    expect(screen.getByRole("status").textContent).toContain("이전 요청이 처리되었는지는 알 수 없습니다");
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
    const closed = { ...openOperations, workflowStatus: "CLOSED" as const, operationsRevision: 2, closedAt: "2026-09-11T00:00:00Z", closedBy: "operator-1", closeNote: "마무리 메모" };
    const fetchMock = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => closed });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkOrderOperationsPanel workOrderId="external-1" principalId="operator-1" initialOperations={openOperations} canWrite accountIdentity={{ fingerprint: `v1-${"f".repeat(64)}` }} />);

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
    render(<WorkOrderOperationsPanel workOrderId="external-1" principalId="operator-1" initialOperations={closed} canWrite accountIdentity={{ fingerprint: `v1-${"f".repeat(64)}` }} />);

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

  it("warns desktop users that the frozen same-key retry is lost on refresh or navigation without deciding the original", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
    const props = { workOrderId: "external-1", principalId: "operator-1", initialOperations: openOperations, accountIdentity: { fingerprint: `v1-${"a".repeat(64)}` } };
    const { rerender } = render(<WorkOrderOperationsPanel {...props} canWrite />);
    fireEvent.click(screen.getByRole("button", { name: "내게 배정" }));
    await screen.findByRole("status");

    // Desktop frozen box carries the explicit same-screen loss warning,
    // distinct from the mobile-only copy (different closing sentence).
    const desktopWarning = "이 요청의 기억은 이 화면에만 있어 새로고침·화면 이동·기기 변경 뒤에는 같은 키로 다시 시도할 수 없습니다. 현재 상태를 먼저 확인하세요.";
    const mobileWarning = "이 요청의 기억은 이 화면에만 있어 새로고침·화면 이동·기기 변경 뒤에는 같은 키로 다시 시도할 수 없습니다. 노트북의 같은 화면에서 원래 기록을 먼저 확인하세요.";
    expect(screen.getAllByText(desktopWarning)).toHaveLength(1);
    expect(screen.getAllByText(mobileWarning)).toHaveLength(1);
    // The warning itself must not decide whether the original was recorded.
    const desktopEl = screen.getByText(desktopWarning);
    expect(desktopEl.textContent).not.toMatch(/기록되었습니다|기록되지 않았습니다|이미 반영된 것을 확인|저장했습니다/);
    expect(screen.getByRole("status").textContent).toContain("응답을 확인하지 못했습니다");
    expect(screen.getByRole("button", { name: "같은 요청 다시 시도" })).not.toBeNull();

    // Write-permission loss keeps the warning but drops the retry control.
    rerender(<WorkOrderOperationsPanel {...props} canWrite={false} />);
    expect(screen.getAllByText(desktopWarning)).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull();
    expect(screen.getByRole("button", { name: "현재 상태 다시 불러오기" })).not.toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
