/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WorkOrderOperationsPanel } from "@/app/field/WorkOrderOperationsPanel";
import { TeamRosterPanel } from "@/app/field/team/TeamRosterPanel";

// jsdom은 Tailwind 브레이크포인트를 계산하지 못하므로, 실제 화면 노출 여부가
// 아니라 클래스 계약(lg:hidden 경고 상자 / hidden lg:contents 데스크 상자)과
// DOM 배치를 검증한다. 계산된 가시성 확인은 CSS 전용 한계로 남긴다.

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

const notifyMock = vi.hoisted(() => vi.fn());
vi.mock("@/components/ui/ToastProvider", () => ({ useToast: () => ({ notify: notifyMock }) }));
vi.mock("@/components/ui/ConfirmDialog", () => ({
  ConfirmDialog: ({ open, title, onConfirm, onCancel }: {
    open: boolean; title: string; onConfirm: () => void; onCancel: () => void;
  }) => open ? (
    <div role="dialog" aria-label={title}>
      <button onClick={onConfirm}>확인</button>
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

describe("frozen recovery mobile warning placement", () => {
  it("keeps an operations read-only warning outside the desktop boundary", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkOrderOperationsPanel workOrderId="external-1" principalId="operator-1" initialOperations={openOperations} canWrite accountIdentity={{ fingerprint: `v1-${"a".repeat(64)}` }} />);
    fireEvent.click(screen.getByRole("button", { name: "내게 배정" }));
    await screen.findByRole("status");

    const warning = screen.getByText(/노트북의 같은 화면에서 원래 기록을 먼저 확인하세요/);
    expect(screen.getByText(/결과는 알 수 없습니다/)).toBeTruthy();
    expect(screen.getByText(/노트북의 같은 화면에서 원래 기록을 먼저 확인하세요/)).toBeTruthy();
    const box = warning.closest("div");
    expect(box).not.toBeNull();
    expect(box!.className.split(" ")).toContain("lg:hidden");
    expect(box!.className.split(" ")).not.toContain("hidden");
    expect(within(box as HTMLElement).queryByRole("button")).toBeNull();

    const retry = screen.getByRole("button", { name: "같은 요청 다시 시도" });
    expect(retry.closest("div.hidden")).not.toBeNull();
    expect(warning.closest("div.hidden")).toBeNull();
  });

  it("keeps a roster read-only warning outside the desktop boundary", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
    render(<TeamRosterPanel initialMembers={[]} canManage currentPrincipalId="admin" organizationId="org-1" accountIdentity={{ fingerprint: `v1-${"c".repeat(64)}` }} />);
    fireEvent.change(screen.getByLabelText("사용자 ID"), { target: { value: "operator-b" } });
    fireEvent.change(screen.getByLabelText("표시 이름"), { target: { value: "현장 담당" } });
    fireEvent.click(screen.getByRole("button", { name: "팀원 정보 저장" }));
    await screen.findByRole("status");

    const warning = screen.getByText(/이 요청의 기억은 이 화면에만 있어/);
    expect(screen.getByText(/팀원 목록의 원래 기록을 먼저 확인하세요/)).toBeTruthy();
    const box = warning.closest("div");
    expect(box).not.toBeNull();
    expect(box!.className.split(" ")).toContain("lg:hidden");
    expect(box!.className.split(" ")).not.toContain("hidden");
    expect(within(box as HTMLElement).queryByRole("button")).toBeNull();

    const retry = screen.getByRole("button", { name: "같은 요청 다시 시도" });
    expect(retry.closest("div.hidden")).not.toBeNull();
    expect(warning.closest("div.hidden")).toBeNull();
  });
});
