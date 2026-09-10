/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TeamRosterPanel } from "@/app/field/team/TeamRosterPanel";

vi.mock("@/components/responsive/ResponsiveActionBoundary", () => ({ ResponsiveActionBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</> }));

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("TeamRosterPanel", () => {
  it("reloads a conflicted member revision while preserving the edited draft", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 409, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ members: [{ principalId: "operator-b", displayName: "서버 이름", roleHint: "VIEWER", status: "INACTIVE", revision: 2, updatedAt: "2026-09-10T00:00:00Z", updatedBy: "admin" }] }) });
    vi.stubGlobal("fetch", fetchMock);
    render(<TeamRosterPanel initialMembers={[{ principalId: "operator-b", displayName: "기존 이름", roleHint: "FIELD_OPERATOR", status: "ACTIVE", revision: 1, updatedAt: "2026-09-10T00:00:00Z", updatedBy: "admin" }]} canManage currentPrincipalId="admin" />);
    fireEvent.click(screen.getByRole("button", { name: "수정" }));
    fireEvent.change(screen.getByLabelText("표시 이름"), { target: { value: "내 수정 이름" } });
    fireEvent.click(screen.getByRole("button", { name: "팀원 정보 저장" }));
    await screen.findByRole("status");
    fireEvent.click(screen.getByRole("button", { name: "최신 팀원 목록 불러오기" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect((screen.getByLabelText("표시 이름") as HTMLInputElement).value).toBe("내 수정 이름");
    fireEvent.click(screen.getByRole("button", { name: "팀원 정보 저장" }));
    await waitFor(() => expect(JSON.parse(fetchMock.mock.calls[2]?.[1]?.body).expectedRevision).toBe(2));
  });
  it("keeps the roster draft and exact idempotency key for an uncertain save retry", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ principalId: "operator-b", displayName: "현장 담당", roleHint: "FIELD_OPERATOR", status: "ACTIVE", revision: 1, updatedAt: "2026-09-10T00:00:00Z", updatedBy: "admin" }) });
    vi.stubGlobal("fetch", fetchMock);
    render(<TeamRosterPanel initialMembers={[]} canManage currentPrincipalId="admin" />);
    fireEvent.change(screen.getByLabelText("사용자 ID"), { target: { value: "operator-b" } });
    fireEvent.change(screen.getByLabelText("표시 이름"), { target: { value: "현장 담당" } });
    fireEvent.click(screen.getByRole("button", { name: "팀원 정보 저장" }));
    await screen.findByRole("status");
    expect(screen.getByRole("button", { name: "같은 요청 다시 시도" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1]?.[1]?.headers["Idempotency-Key"]).toBe(fetchMock.mock.calls[0]?.[1]?.headers["Idempotency-Key"]);
    expect(screen.getByText("현장 담당")).toBeTruthy();
  });

  it("freezes roster editing while an uncertain save waits for its exact retry", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
    render(<TeamRosterPanel initialMembers={[{ principalId: "operator-a", displayName: "기존 담당", roleHint: "FIELD_OPERATOR", status: "ACTIVE", revision: 1, updatedAt: "2026-09-10T00:00:00Z", updatedBy: "admin" }]} canManage currentPrincipalId="admin" />);
    fireEvent.click(screen.getByRole("button", { name: "수정" }));
    fireEvent.click(screen.getByRole("button", { name: "팀원 정보 저장" }));
    await screen.findByRole("status");
    expect((screen.getByLabelText("사용자 ID") as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByLabelText("표시 이름") as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "수정" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "같은 요청 다시 시도" }) as HTMLButtonElement).disabled).toBe(false);
  });
});
