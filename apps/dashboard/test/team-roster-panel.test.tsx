/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TeamRosterPanel } from "@/app/field/team/TeamRosterPanel";

vi.mock("@/components/responsive/ResponsiveActionBoundary", () => ({ ResponsiveActionBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</> }));

const notifyMock = vi.hoisted(() => vi.fn());
vi.mock("@/components/ui/ToastProvider", () => ({ useToast: () => ({ notify: notifyMock }) }));
vi.mock("@/components/ui/ActionUnavailable", () => ({
  ActionUnavailable: ({ label, description }: { label: string; description: string }) => (
    <div><span>{label}</span><span>{description}</span></div>
  ),
}));

afterEach(() => { cleanup(); vi.unstubAllGlobals(); notifyMock.mockClear(); });

describe("TeamRosterPanel", () => {
  it("reloads a conflicted member revision while preserving the edited draft", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 409, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ members: [{ schemaVersion: "1.0", organizationId: "org-1", principalId: "operator-b", displayName: "서버 이름", roleHint: "VIEWER", status: "INACTIVE", revision: 2, updatedAt: "2026-09-10T00:00:00Z", updatedBy: "admin" }] }) });
    vi.stubGlobal("fetch", fetchMock);
    render(<TeamRosterPanel initialMembers={[{ schemaVersion: "1.0", organizationId: "org-1", principalId: "operator-b", displayName: "기존 이름", roleHint: "FIELD_OPERATOR", status: "ACTIVE", revision: 1, updatedAt: "2026-09-10T00:00:00Z", updatedBy: "admin" }]} canManage currentPrincipalId="admin" organizationId="org-1" accountIdentity={{ fingerprint: `v1-${"c".repeat(64)}` }} />);
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
  it("keeps viewer and manager empty states distinct without implying an account grant", () => {
    const { unmount } = render(<TeamRosterPanel initialMembers={[]} canManage currentPrincipalId="admin" organizationId="org-1" />);
    expect(screen.getByText(/추가할 수 있습니다/)).toBeTruthy();
    unmount();
    cleanup();
    render(<TeamRosterPanel initialMembers={[]} canManage={false} currentPrincipalId="operator-a" organizationId="org-1" />);
    expect(screen.getByText(/등록된 팀원 정보가 없습니다/)).toBeTruthy();
    expect(document.body.textContent).not.toContain("추가할 수 있습니다");
  });
  it("keeps the roster draft and exact idempotency key for an uncertain save retry", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ schemaVersion: "1.0", organizationId: "org-1", principalId: "operator-b", displayName: "현장 담당", roleHint: "FIELD_OPERATOR", status: "ACTIVE", revision: 1, updatedAt: "2026-09-10T00:00:00Z", updatedBy: "admin" }) });
    vi.stubGlobal("fetch", fetchMock);
    render(<TeamRosterPanel initialMembers={[]} canManage currentPrincipalId="admin" organizationId="org-1" accountIdentity={{ fingerprint: `v1-${"c".repeat(64)}` }} />);
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
    render(<TeamRosterPanel initialMembers={[{ schemaVersion: "1.0", organizationId: "org-1", principalId: "operator-a", displayName: "기존 담당", roleHint: "FIELD_OPERATOR", status: "ACTIVE", revision: 1, updatedAt: "2026-09-10T00:00:00Z", updatedBy: "admin" }]} canManage currentPrincipalId="admin" organizationId="org-1" accountIdentity={{ fingerprint: `v1-${"c".repeat(64)}` }} />);
    fireEvent.click(screen.getByRole("button", { name: "수정" }));
    fireEvent.click(screen.getByRole("button", { name: "팀원 정보 저장" }));
    await screen.findByRole("status");
    expect((screen.getByLabelText("사용자 ID") as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByLabelText("표시 이름") as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "수정" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "같은 요청 다시 시도" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("keeps the frozen roster request when a same-key retry is denied and allows explicit discard", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: false, status: 403, json: async () => ({ message: "권한이 부족하다" }) });
    vi.stubGlobal("fetch", fetchMock);
    render(<TeamRosterPanel initialMembers={[]} canManage currentPrincipalId="admin" organizationId="org-1" accountIdentity={{ fingerprint: `v1-${"c".repeat(64)}` }} />);
    fireEvent.change(screen.getByLabelText("사용자 ID"), { target: { value: "operator-b" } });
    fireEvent.change(screen.getByLabelText("표시 이름"), { target: { value: "현장 담당" } });
    fireEvent.click(screen.getByRole("button", { name: "팀원 정보 저장" }));
    await screen.findByRole("status");
    expect(screen.getByRole("button", { name: "같은 요청 다시 시도" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1]?.[1]?.headers["Idempotency-Key"]).toBe(fetchMock.mock.calls[0]?.[1]?.headers["Idempotency-Key"]);
    expect(fetchMock.mock.calls[1]?.[1]?.headers["x-ksi-continuity-fingerprint"]).toBe(fetchMock.mock.calls[0]?.[1]?.headers["x-ksi-continuity-fingerprint"]);
    expect(JSON.parse(fetchMock.mock.calls[1]?.[1]?.body)).toEqual(JSON.parse(fetchMock.mock.calls[0]?.[1]?.body));
    expect(decodeURIComponent(fetchMock.mock.calls[1]?.[0] as string)).toContain("operator-b");
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).not.toBeNull();
    expect(screen.getByRole("status").textContent).toContain("이전 요청이 처리되었는지는 알 수 없습니다");
    expect(screen.getByRole("status").textContent).not.toContain("입력을 확인하고 다시 시도하세요");

    fireEvent.click(screen.getByRole("button", { name: "동결된 요청 버리기" }));
    expect(screen.getByRole("button", { name: "버리기 확인" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "취소" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(2);

    fireEvent.click(screen.getByRole("button", { name: "취소" }));
    expect(screen.queryByRole("button", { name: "버리기 확인" })).toBeNull();
    expect(screen.getByRole("button", { name: "같은 요청 다시 시도" })).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(2);

    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(fetchMock.mock.calls[2]?.[1]?.headers["Idempotency-Key"]).toBe(fetchMock.mock.calls[0]?.[1]?.headers["Idempotency-Key"]);

    fireEvent.click(screen.getByRole("button", { name: "동결된 요청 버리기" }));
    fireEvent.click(screen.getByRole("button", { name: "버리기 확인" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull());
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(screen.getByRole("status").textContent).toContain("버린 요청이 처리되었는지는 알 수 없");
    expect(screen.getByRole("status").textContent).toContain("새 요청으로 기록됩니다");
  });

  it("freezes an unproven roster status with same-key recovery", async () => {
    const saved = { schemaVersion: "1.0", organizationId: "org-1", principalId: "operator-b", displayName: "현장 담당", roleHint: "FIELD_OPERATOR", status: "ACTIVE", revision: 1, updatedAt: "2026-09-10T00:00:00Z", updatedBy: "admin" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 418, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => saved });
    vi.stubGlobal("fetch", fetchMock);
    render(<TeamRosterPanel initialMembers={[]} canManage currentPrincipalId="admin" organizationId="org-1" accountIdentity={{ fingerprint: `v1-${"c".repeat(64)}` }} />);
    fireEvent.change(screen.getByLabelText("사용자 ID"), { target: { value: "operator-b" } });
    fireEvent.change(screen.getByLabelText("표시 이름"), { target: { value: "현장 담당" } });
    fireEvent.click(screen.getByRole("button", { name: "팀원 정보 저장" }));
    await screen.findByRole("status");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).not.toBeNull();
    expect(screen.getByRole("status").textContent).toContain("기록 여부를 확인할 수 없");
    expect(notifyMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1]?.[1]?.headers["Idempotency-Key"]).toBe(fetchMock.mock.calls[0]?.[1]?.headers["Idempotency-Key"]);
    expect(JSON.parse(fetchMock.mock.calls[1]?.[1]?.body)).toEqual(JSON.parse(fetchMock.mock.calls[0]?.[1]?.body));
    expect(decodeURIComponent(fetchMock.mock.calls[1]?.[0] as string)).toContain("operator-b");
    await waitFor(() => expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull());
    expect(notifyMock).toHaveBeenCalledWith("팀원 정보를 저장했습니다.");
  });

  it("freezes a bare roster 400 as unknown and recovers with the same key", async () => {
    const saved = { schemaVersion: "1.0", organizationId: "org-1", principalId: "operator-b", displayName: "현장 담당", roleHint: "FIELD_OPERATOR", status: "ACTIVE", revision: 1, updatedAt: "2026-09-10T00:00:00Z", updatedBy: "admin" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 400, json: async () => ({ message: "팀원 정보 형식이 올바르지 않습니다." }) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => saved });
    vi.stubGlobal("fetch", fetchMock);
    render(<TeamRosterPanel initialMembers={[]} canManage currentPrincipalId="admin" organizationId="org-1" accountIdentity={{ fingerprint: `v1-${"c".repeat(64)}` }} />);
    fireEvent.change(screen.getByLabelText("사용자 ID"), { target: { value: "operator-b" } });
    fireEvent.change(screen.getByLabelText("표시 이름"), { target: { value: "현장 담당" } });
    fireEvent.click(screen.getByRole("button", { name: "팀원 정보 저장" }));
    await screen.findByRole("status");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).not.toBeNull();
    expect(screen.getByRole("status").textContent).toContain("기록 여부를 확인할 수 없");

    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1]?.[1]?.headers["Idempotency-Key"]).toBe(fetchMock.mock.calls[0]?.[1]?.headers["Idempotency-Key"]);
    await waitFor(() => expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull());
  });

  it("keeps the roster freeze on a malformed success payload and recovers with the same key", async () => {
    const saved = { schemaVersion: "1.0", organizationId: "org-1", principalId: "operator-b", displayName: "현장 담당", roleHint: "FIELD_OPERATOR", status: "ACTIVE", revision: 1, updatedAt: "2026-09-10T00:00:00Z", updatedBy: "admin" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => saved });
    vi.stubGlobal("fetch", fetchMock);
    render(<TeamRosterPanel initialMembers={[]} canManage currentPrincipalId="admin" organizationId="org-1" accountIdentity={{ fingerprint: `v1-${"c".repeat(64)}` }} />);
    fireEvent.change(screen.getByLabelText("사용자 ID"), { target: { value: "operator-b" } });
    fireEvent.change(screen.getByLabelText("표시 이름"), { target: { value: "현장 담당" } });
    fireEvent.click(screen.getByRole("button", { name: "팀원 정보 저장" }));
    await screen.findByRole("status");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).not.toBeNull();
    expect(screen.getByRole("status").textContent).toContain("기록 여부는 알 수 없습니다");
    expect(notifyMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1]?.[1]?.headers["Idempotency-Key"]).toBe(fetchMock.mock.calls[0]?.[1]?.headers["Idempotency-Key"]);
    await waitFor(() => expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull());
    expect(notifyMock).toHaveBeenCalledWith("팀원 정보를 저장했습니다.");
  });

  it("keeps the roster freeze on same-principal content that does not match the request", async () => {
    const mismatched = { schemaVersion: "1.0", organizationId: "org-1", principalId: "operator-b", displayName: "다른 이름", roleHint: "VIEWER", status: "ACTIVE", revision: 1, updatedAt: "2026-09-10T00:00:00Z", updatedBy: "admin" };
    const saved = { schemaVersion: "1.0", organizationId: "org-1", principalId: "operator-b", displayName: "현장 담당", roleHint: "FIELD_OPERATOR", status: "ACTIVE", revision: 1, updatedAt: "2026-09-10T00:00:00Z", updatedBy: "admin" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => mismatched })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => saved });
    vi.stubGlobal("fetch", fetchMock);
    render(<TeamRosterPanel initialMembers={[]} canManage currentPrincipalId="admin" organizationId="org-1" accountIdentity={{ fingerprint: `v1-${"c".repeat(64)}` }} />);
    fireEvent.change(screen.getByLabelText("사용자 ID"), { target: { value: "operator-b" } });
    fireEvent.change(screen.getByLabelText("표시 이름"), { target: { value: "현장 담당" } });
    fireEvent.click(screen.getByRole("button", { name: "팀원 정보 저장" }));
    await screen.findByRole("status");

    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).not.toBeNull();
    expect(screen.getByRole("status").textContent).toContain("기록 여부는 알 수 없습니다");
    expect(notifyMock).not.toHaveBeenCalled();
    expect(screen.queryByText("다른 이름")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(fetchMock.mock.calls[2]?.[1]?.headers["Idempotency-Key"]).toBe(fetchMock.mock.calls[0]?.[1]?.headers["Idempotency-Key"]);
    await waitFor(() => expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull());
    expect(notifyMock).toHaveBeenCalledWith("팀원 정보를 저장했습니다.");
  });

  it("keeps the roster freeze on a same-principal response with a wrong revision", async () => {
    const future = { schemaVersion: "1.0", organizationId: "org-1", principalId: "operator-b", displayName: "현장 담당", roleHint: "FIELD_OPERATOR", status: "ACTIVE", revision: 2, updatedAt: "2026-09-10T00:00:00Z", updatedBy: "admin" };
    const saved = { schemaVersion: "1.0", organizationId: "org-1", principalId: "operator-b", displayName: "현장 담당", roleHint: "FIELD_OPERATOR", status: "ACTIVE", revision: 1, updatedAt: "2026-09-10T00:00:00Z", updatedBy: "admin" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => future })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => saved });
    vi.stubGlobal("fetch", fetchMock);
    render(<TeamRosterPanel initialMembers={[]} canManage currentPrincipalId="admin" organizationId="org-1" accountIdentity={{ fingerprint: `v1-${"c".repeat(64)}` }} />);
    fireEvent.change(screen.getByLabelText("사용자 ID"), { target: { value: "operator-b" } });
    fireEvent.change(screen.getByLabelText("표시 이름"), { target: { value: "현장 담당" } });
    fireEvent.click(screen.getByRole("button", { name: "팀원 정보 저장" }));
    await screen.findByRole("status");

    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).not.toBeNull();
    expect(screen.getByRole("status").textContent).toContain("기록 여부는 알 수 없습니다");
    expect(notifyMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull());
    expect(notifyMock).toHaveBeenCalledWith("팀원 정보를 저장했습니다.");
  });

  it("confirms the original roster request without regressing a newer list", async () => {
    const newer = { schemaVersion: "1.0", organizationId: "org-1", principalId: "operator-b", displayName: "서버 이름", roleHint: "VIEWER", status: "ACTIVE", revision: 2, updatedAt: "2026-09-10T00:00:00Z", updatedBy: "admin" };
    const replay = { schemaVersion: "1.0", organizationId: "org-1", principalId: "operator-b", displayName: "현장 담당", roleHint: "FIELD_OPERATOR", status: "ACTIVE", revision: 1, updatedAt: "2026-09-10T00:00:00Z", updatedBy: "admin" };
    const fingerprint = `v1-${"c".repeat(64)}`;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ members: [newer] }) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => replay });
    vi.stubGlobal("fetch", fetchMock);
    render(<TeamRosterPanel initialMembers={[]} canManage currentPrincipalId="admin" organizationId="org-1" accountIdentity={{ fingerprint }} />);
    fireEvent.change(screen.getByLabelText("사용자 ID"), { target: { value: "operator-b" } });
    fireEvent.change(screen.getByLabelText("표시 이름"), { target: { value: "현장 담당" } });
    fireEvent.click(screen.getByRole("button", { name: "팀원 정보 저장" }));
    await screen.findByRole("status");

    fireEvent.click(screen.getByRole("button", { name: "최신 팀원 목록 불러오기" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(screen.getByText("서버 이름")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(fetchMock.mock.calls[2]?.[1]?.headers["Idempotency-Key"]).toBe(fetchMock.mock.calls[0]?.[1]?.headers["Idempotency-Key"]);
    expect(fetchMock.mock.calls[2]?.[1]?.headers["x-ksi-continuity-fingerprint"]).toBe(fingerprint);
    await waitFor(() => expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull());
    expect(screen.getByText("서버 이름")).toBeTruthy();
    expect(screen.queryByText("현장 담당")).toBeNull();
    expect(screen.getByRole("status").textContent).toContain("원래 요청이 이미 반영된 것");
    expect(notifyMock).not.toHaveBeenCalledWith("팀원 정보를 저장했습니다.");
  });

  it("keeps read-only roster recovery without retry when manage permission is lost", async () => {
    const reloaded = { schemaVersion: "1.0", organizationId: "org-1", principalId: "operator-b", displayName: "서버 이름", roleHint: "FIELD_OPERATOR", status: "ACTIVE", revision: 1, updatedAt: "2026-09-10T00:00:00Z", updatedBy: "admin" };
    const replay = { schemaVersion: "1.0", organizationId: "org-1", principalId: "operator-b", displayName: "현장 담당", roleHint: "FIELD_OPERATOR", status: "ACTIVE", revision: 1, updatedAt: "2026-09-10T00:00:00Z", updatedBy: "admin" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ members: [reloaded] }) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => replay });
    vi.stubGlobal("fetch", fetchMock);
    const props = { initialMembers: [] as never[], currentPrincipalId: "admin", organizationId: "org-1", accountIdentity: { fingerprint: `v1-${"c".repeat(64)}` } };
    const { rerender } = render(<TeamRosterPanel {...props} canManage />);
    fireEvent.change(screen.getByLabelText("사용자 ID"), { target: { value: "operator-b" } });
    fireEvent.change(screen.getByLabelText("표시 이름"), { target: { value: "현장 담당" } });
    fireEvent.click(screen.getByRole("button", { name: "팀원 정보 저장" }));
    await screen.findByRole("status");
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).not.toBeNull();

    rerender(<TeamRosterPanel {...props} canManage={false} />);
    expect(screen.getByText(/이미 반영됐을 수 있습니다/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull();
    expect(screen.queryByRole("button", { name: "팀원 정보 저장" })).toBeNull();
    expect(screen.getByRole("button", { name: "최신 팀원 목록 불러오기" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "동결된 요청 버리기" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "최신 팀원 목록 불러오기" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1]?.[1]?.method).toBeUndefined();
    expect(String(fetchMock.mock.calls[1]?.[0])).not.toContain("/organization-work-roster/operator-b");
    expect(screen.getByText(/이미 반영됐을 수 있습니다/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull();

    rerender(<TeamRosterPanel {...props} canManage />);
    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(fetchMock.mock.calls[2]?.[1]?.headers["Idempotency-Key"]).toBe(fetchMock.mock.calls[0]?.[1]?.headers["Idempotency-Key"]);
    await waitFor(() => expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull());
    expect(notifyMock).toHaveBeenCalledWith("팀원 정보를 저장했습니다.");
  });

  it("binds roster success to the frozen actor even when the live user prop changes", async () => {
    const replay = { schemaVersion: "1.0", organizationId: "org-1", principalId: "operator-b", displayName: "현장 담당", roleHint: "FIELD_OPERATOR", status: "ACTIVE", revision: 1, updatedAt: "2026-09-10T00:00:00Z", updatedBy: "admin" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => replay });
    vi.stubGlobal("fetch", fetchMock);
    const { rerender } = render(<TeamRosterPanel initialMembers={[]} canManage currentPrincipalId="admin" organizationId="org-1" accountIdentity={{ fingerprint: `v1-${"c".repeat(64)}` }} />);
    fireEvent.change(screen.getByLabelText("사용자 ID"), { target: { value: "operator-b" } });
    fireEvent.change(screen.getByLabelText("표시 이름"), { target: { value: "현장 담당" } });
    fireEvent.click(screen.getByRole("button", { name: "팀원 정보 저장" }));
    await screen.findByRole("status");

    rerender(<TeamRosterPanel initialMembers={[]} canManage currentPrincipalId="operator-9" organizationId="org-1" accountIdentity={{ fingerprint: `v1-${"c".repeat(64)}` }} />);
    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull());
    expect(notifyMock).toHaveBeenCalledWith("팀원 정보를 저장했습니다.");
  });

  it("keeps the roster list and freeze when reload returns a malformed payload", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ members: [{ principalId: 123 }] }) });
    vi.stubGlobal("fetch", fetchMock);
    render(<TeamRosterPanel initialMembers={[]} canManage currentPrincipalId="admin" organizationId="org-1" accountIdentity={{ fingerprint: `v1-${"c".repeat(64)}` }} />);
    fireEvent.change(screen.getByLabelText("사용자 ID"), { target: { value: "operator-b" } });
    fireEvent.change(screen.getByLabelText("표시 이름"), { target: { value: "현장 담당" } });
    fireEvent.click(screen.getByRole("button", { name: "팀원 정보 저장" }));
    await screen.findByRole("status");

    fireEvent.click(screen.getByRole("button", { name: "최신 팀원 목록 불러오기" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).not.toBeNull();
    expect(screen.getByRole("status").textContent).toContain("불러오지 못했습니다");
    expect(screen.getByText(/추가할 수 있습니다/)).toBeTruthy();
  });

  it("freezes a same-principal echo from a different organization", async () => {
    const foreign = { schemaVersion: "1.0", organizationId: "org-x", principalId: "operator-b", displayName: "현장 담당", roleHint: "FIELD_OPERATOR", status: "ACTIVE", revision: 1, updatedAt: "2026-09-10T00:00:00Z", updatedBy: "admin" };
    const saved = { schemaVersion: "1.0", organizationId: "org-1", principalId: "operator-b", displayName: "현장 담당", roleHint: "FIELD_OPERATOR", status: "ACTIVE", revision: 1, updatedAt: "2026-09-10T00:00:00Z", updatedBy: "admin" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => foreign })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => saved });
    vi.stubGlobal("fetch", fetchMock);
    render(<TeamRosterPanel initialMembers={[]} canManage currentPrincipalId="admin" organizationId="org-1" accountIdentity={{ fingerprint: `v1-${"c".repeat(64)}` }} />);
    fireEvent.change(screen.getByLabelText("사용자 ID"), { target: { value: "operator-b" } });
    fireEvent.change(screen.getByLabelText("표시 이름"), { target: { value: "현장 담당" } });
    fireEvent.click(screen.getByRole("button", { name: "팀원 정보 저장" }));
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
    expect(notifyMock).toHaveBeenCalledWith("팀원 정보를 저장했습니다.");
  });

  it("freezes a same-principal reply missing the updater audit field", async () => {
    const noAudit = { schemaVersion: "1.0", organizationId: "org-1", principalId: "operator-b", displayName: "현장 담당", roleHint: "FIELD_OPERATOR", status: "ACTIVE", revision: 1, updatedAt: "2026-09-10T00:00:00Z" };
    const saved = { schemaVersion: "1.0", organizationId: "org-1", principalId: "operator-b", displayName: "현장 담당", roleHint: "FIELD_OPERATOR", status: "ACTIVE", revision: 1, updatedAt: "2026-09-10T00:00:00Z", updatedBy: "admin" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => noAudit })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => saved });
    vi.stubGlobal("fetch", fetchMock);
    render(<TeamRosterPanel initialMembers={[]} canManage currentPrincipalId="admin" organizationId="org-1" accountIdentity={{ fingerprint: `v1-${"c".repeat(64)}` }} />);
    fireEvent.change(screen.getByLabelText("사용자 ID"), { target: { value: "operator-b" } });
    fireEvent.change(screen.getByLabelText("표시 이름"), { target: { value: "현장 담당" } });
    fireEvent.click(screen.getByRole("button", { name: "팀원 정보 저장" }));
    await screen.findByRole("status");

    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).not.toBeNull();
    expect(screen.getByRole("status").textContent).toContain("기록 여부는 알 수 없습니다");
    expect(notifyMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull());
    expect(notifyMock).toHaveBeenCalledWith("팀원 정보를 저장했습니다.");
  });

  it("keeps the roster freeze on a success echo for a different member", async () => {
    const other = { schemaVersion: "1.0", organizationId: "org-1", principalId: "operator-z", displayName: "다른 담당", roleHint: "FIELD_OPERATOR", status: "ACTIVE", revision: 1, updatedAt: "2026-09-10T00:00:00Z", updatedBy: "admin" };
    const saved = { schemaVersion: "1.0", organizationId: "org-1", principalId: "operator-b", displayName: "현장 담당", roleHint: "FIELD_OPERATOR", status: "ACTIVE", revision: 1, updatedAt: "2026-09-10T00:00:00Z", updatedBy: "admin" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => other })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => saved });
    vi.stubGlobal("fetch", fetchMock);
    render(<TeamRosterPanel initialMembers={[]} canManage currentPrincipalId="admin" organizationId="org-1" accountIdentity={{ fingerprint: `v1-${"c".repeat(64)}` }} />);
    fireEvent.change(screen.getByLabelText("사용자 ID"), { target: { value: "operator-b" } });
    fireEvent.change(screen.getByLabelText("표시 이름"), { target: { value: "현장 담당" } });
    fireEvent.click(screen.getByRole("button", { name: "팀원 정보 저장" }));
    await screen.findByRole("status");

    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).not.toBeNull();
    expect(screen.getByRole("status").textContent).toContain("기록 여부는 알 수 없습니다");
    expect(notifyMock).not.toHaveBeenCalled();
    expect(screen.queryByText("다른 담당")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(fetchMock.mock.calls[2]?.[1]?.headers["Idempotency-Key"]).toBe(fetchMock.mock.calls[0]?.[1]?.headers["Idempotency-Key"]);
    await waitFor(() => expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull());
    expect(notifyMock).toHaveBeenCalledWith("팀원 정보를 저장했습니다.");
  });

  it("shows the roster discard consequence before any discard choice", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
    render(<TeamRosterPanel initialMembers={[]} canManage currentPrincipalId="admin" organizationId="org-1" accountIdentity={{ fingerprint: `v1-${"c".repeat(64)}` }} />);
    fireEvent.change(screen.getByLabelText("사용자 ID"), { target: { value: "operator-b" } });
    fireEvent.change(screen.getByLabelText("표시 이름"), { target: { value: "현장 담당" } });
    fireEvent.click(screen.getByRole("button", { name: "팀원 정보 저장" }));
    await screen.findByRole("status");
    expect(screen.getByText(/이미 반영됐을 수 있습니다/)).toBeTruthy();
    expect(screen.getByText(/새 요청\(새 키\)으로 기록됩니다/)).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("blocks a new roster save when the server-derived identity is missing or malformed", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const { unmount } = render(<TeamRosterPanel initialMembers={[]} canManage currentPrincipalId="admin" organizationId="org-1" />);
    fireEvent.change(screen.getByLabelText("사용자 ID"), { target: { value: "operator-b" } });
    fireEvent.change(screen.getByLabelText("표시 이름"), { target: { value: "현장 담당" } });
    fireEvent.click(screen.getByRole("button", { name: "팀원 정보 저장" }));
    await screen.findByRole("status");
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByRole("status").textContent).toContain("계정을 확인하지 못해 새 저장을 시작할 수 없습니다");
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull();
    unmount();
    cleanup();

    render(<TeamRosterPanel initialMembers={[]} canManage currentPrincipalId="admin" organizationId="org-1" accountIdentity={{ fingerprint: "broken" }} />);
    fireEvent.change(screen.getByLabelText("사용자 ID"), { target: { value: "operator-b" } });
    fireEvent.change(screen.getByLabelText("표시 이름"), { target: { value: "현장 담당" } });
    fireEvent.click(screen.getByRole("button", { name: "팀원 정보 저장" }));
    await screen.findByRole("status");
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByRole("status").textContent).toContain("계정을 확인하지 못해 새 저장을 시작할 수 없습니다");
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull();
  });

  it("retries a preserved roster request with its original continuity when current identity is missing", async () => {
    const fingerprint = `v1-${"e".repeat(64)}`;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ schemaVersion: "1.0", organizationId: "org-1", principalId: "operator-b", displayName: "현장 담당", roleHint: "FIELD_OPERATOR", status: "ACTIVE", revision: 1, updatedAt: "2026-09-10T00:00:00Z", updatedBy: "admin" }) });
    vi.stubGlobal("fetch", fetchMock);
    const props = { initialMembers: [] as never[], canManage: true as const, currentPrincipalId: "admin", organizationId: "org-1" };
    const { rerender } = render(<TeamRosterPanel {...props} accountIdentity={{ fingerprint }} />);
    fireEvent.change(screen.getByLabelText("사용자 ID"), { target: { value: "operator-b" } });
    fireEvent.change(screen.getByLabelText("표시 이름"), { target: { value: "현장 담당" } });
    fireEvent.click(screen.getByRole("button", { name: "팀원 정보 저장" }));
    await screen.findByRole("status");
    expect(screen.getByRole("button", { name: "같은 요청 다시 시도" })).toBeTruthy();

    rerender(<TeamRosterPanel {...props} accountIdentity={null} />);
    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1]?.[1]?.headers["x-ksi-continuity-fingerprint"]).toBe(fingerprint);
    expect(fetchMock.mock.calls[1]?.[1]?.headers["Idempotency-Key"]).toBe(fetchMock.mock.calls[0]?.[1]?.headers["Idempotency-Key"]);
    await waitFor(() => expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull());
  });

  it("keeps the roster freeze when the account changes between attempts", async () => {
    const fingerprint = `v1-${"d".repeat(64)}`;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: false, status: 409, json: async () => ({ code: "ACCOUNT_CONTINUITY_MISMATCH" }) });
    vi.stubGlobal("fetch", fetchMock);
    render(<TeamRosterPanel initialMembers={[]} canManage currentPrincipalId="admin" organizationId="org-1" accountIdentity={{ fingerprint }} />);
    fireEvent.change(screen.getByLabelText("사용자 ID"), { target: { value: "operator-b" } });
    fireEvent.change(screen.getByLabelText("표시 이름"), { target: { value: "현장 담당" } });
    fireEvent.click(screen.getByRole("button", { name: "팀원 정보 저장" }));
    await screen.findByRole("status");

    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1]?.[1]?.headers["x-ksi-continuity-fingerprint"]).toBe(fingerprint);
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).not.toBeNull();
    expect(screen.getByRole("status").textContent).toContain("계정이 바뀌어");
    expect(screen.getByRole("status").textContent).toContain("이전 요청이 처리되었는지는 알 수 없습니다");
  });
  it("toasts a confirmed save while keeping the registration-is-not-an-account context", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ schemaVersion: "1.0", organizationId: "org-1", principalId: "operator-b", displayName: "현장 담당", roleHint: "FIELD_OPERATOR", status: "ACTIVE", revision: 1, updatedAt: "2026-09-10T00:00:00Z", updatedBy: "admin" }) });
    vi.stubGlobal("fetch", fetchMock);
    render(<TeamRosterPanel initialMembers={[]} canManage currentPrincipalId="admin" organizationId="org-1" accountIdentity={{ fingerprint: `v1-${"c".repeat(64)}` }} />);
    fireEvent.change(screen.getByLabelText("사용자 ID"), { target: { value: "operator-b" } });
    fireEvent.change(screen.getByLabelText("표시 이름"), { target: { value: "현장 담당" } });
    fireEvent.click(screen.getByRole("button", { name: "팀원 정보 저장" }));
    await waitFor(() => expect(notifyMock).toHaveBeenCalledWith("팀원 정보를 저장했습니다."));
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.getByText(/계정 생성·로그인 초대·권한 부여는 여기서 하지 않습니다/)).toBeTruthy();
  });

  it("shows a click-blocked registration action when the roster itself stays read-only", () => {
    render(<TeamRosterPanel initialMembers={[{ schemaVersion: "1.0", organizationId: "org-1", principalId: "operator-a", displayName: "기존 담당", roleHint: "FIELD_OPERATOR", status: "ACTIVE", revision: 1, updatedAt: "2026-09-10T00:00:00Z", updatedBy: "admin" }]} canManage={false} currentPrincipalId="operator-a" organizationId="org-1" />);
    expect(screen.getByText("기존 담당")).toBeTruthy();
    expect(screen.getByText("팀원 등록/관리")).toBeTruthy();
    expect(screen.getByText("팀 관리에는 관리자 권한이 필요합니다.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "팀원 정보 저장" })).toBeNull();
  });
});
