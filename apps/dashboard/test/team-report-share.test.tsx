/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TeamReportShare } from "@/components/external-results/TeamReportShare";

const share = <TeamReportShare reportRef="report-1" siteId="site-1" organizationId="org-1" principalId="operator-a" canWrite />;

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("TeamReportShare", () => {
  it("lists active recipients including viewers and sends a recipient-only share intent", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ members: [
        { principalId: "operator-a", displayName: "현장 담당", roleHint: "FIELD_OPERATOR", status: "ACTIVE", revision: 1, organizationId: "org-1", schemaVersion: "1.0", updatedAt: "2026-09-10T00:00:00Z", updatedBy: "admin" },
        { principalId: "viewer-a", displayName: "열람자", roleHint: "VIEWER", status: "ACTIVE", revision: 1, organizationId: "org-1", schemaVersion: "1.0", updatedAt: "2026-09-10T00:00:00Z", updatedBy: "admin" },
      ] }) })
      .mockResolvedValueOnce({ ok: true, status: 201, json: async () => ({ schemaVersion: "1.0", shareRef: "share-1", organizationId: "org-1", senderPrincipalId: "operator-a", recipientPrincipalId: "operator-a", siteId: "site-1", reportRef: "report-1", reportDigest: "digest-1", createdAt: "2026-09-10T00:00:00Z" }) });
    vi.stubGlobal("fetch", fetchMock);
    render(share);
    await screen.findByRole("option", { name: /현장 담당/ });
    expect(screen.getByRole("option", { name: /열람자/ })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("공유할 팀원"), { target: { value: "operator-a" } });
    fireEvent.click(screen.getByRole("button", { name: "팀원에게 결과 공유" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/external-relative-volume-reports/report-1/shares");
    expect(JSON.parse(fetchMock.mock.calls[1]?.[1]?.body)).toEqual({ recipientPrincipalId: "operator-a" });
  });

  it("does not claim delivery when Core returns a receipt for another report or recipient", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ members: [{ principalId: "operator-a", displayName: "현장 담당", roleHint: "FIELD_OPERATOR", status: "ACTIVE" }] }) })
      .mockResolvedValueOnce({ ok: true, status: 201, json: async () => ({ schemaVersion: "1.0", shareRef: "share-1", organizationId: "org-1", senderPrincipalId: "operator-a", recipientPrincipalId: "operator-b", siteId: "site-1", reportRef: "other-report", reportDigest: "digest-1", createdAt: "2026-09-10T00:00:00Z" }) })
      .mockResolvedValueOnce({ ok: true, status: 201, json: async () => ({ schemaVersion: "1.0", shareRef: "share-1", organizationId: "org-1", senderPrincipalId: "operator-a", recipientPrincipalId: "operator-a", siteId: "site-1", reportRef: "report-1", reportDigest: "digest-1", createdAt: "2026-09-10T00:00:00Z" }) });
    vi.stubGlobal("fetch", fetchMock);
    render(share);
    await screen.findByRole("option", { name: /현장 담당/ });
    fireEvent.change(screen.getByLabelText("공유할 팀원"), { target: { value: "operator-a" } });
    fireEvent.click(screen.getByRole("button", { name: "팀원에게 결과 공유" }));
    await screen.findByRole("status");
    expect(screen.getByRole("status").textContent).not.toContain("받은 업무에 전달했습니다");
    await waitFor(() => expect((screen.getByRole("button", { name: /같은 요청 다시 시도/ }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.change(screen.getByLabelText("공유할 팀원"), { target: { value: "operator-b" } });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect((screen.getByLabelText("공유할 팀원") as HTMLSelectElement).disabled).toBe(true);
  });

  it("uses a synchronous lock to collapse rapid duplicate share clicks", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ members: [{ principalId: "operator-a", displayName: "현장 담당", roleHint: "FIELD_OPERATOR", status: "ACTIVE" }] }) }).mockImplementationOnce(() => new Promise(() => undefined));
    vi.stubGlobal("fetch", fetchMock);
    render(share);
    await screen.findByRole("option", { name: /현장 담당/ });
    fireEvent.change(screen.getByLabelText("공유할 팀원"), { target: { value: "operator-a" } });
    const button = screen.getByRole("button", { name: "팀원에게 결과 공유" });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("retries a failed roster load instead of leaving the retry action disabled", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ members: [{ principalId: "operator-a", displayName: "현장 담당", roleHint: "FIELD_OPERATOR", status: "ACTIVE" }] }) });
    vi.stubGlobal("fetch", fetchMock);
    render(share);
    const retry = await screen.findByRole("button", { name: "팀원 목록 다시 불러오기" });
    await waitFor(() => expect((retry as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(retry);
    await screen.findByRole("option", { name: /현장 담당/ });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("freezes an ambiguous share to its original recipient and key", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ members: [{ principalId: "operator-a", displayName: "A", roleHint: "FIELD_OPERATOR", status: "ACTIVE" }, { principalId: "operator-b", displayName: "B", roleHint: "FIELD_OPERATOR", status: "ACTIVE" }] }) })
      .mockResolvedValueOnce({ ok: false, status: 504, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
    render(share);
    await screen.findByRole("option", { name: /A · operator-a/ });
    fireEvent.change(screen.getByLabelText("공유할 팀원"), { target: { value: "operator-a" } });
    fireEvent.click(screen.getByRole("button", { name: "팀원에게 결과 공유" }));
    await screen.findByRole("status");
    fireEvent.change(screen.getByLabelText("공유할 팀원"), { target: { value: "operator-b" } });
    fireEvent.click(screen.getByRole("button", { name: /같은 요청 다시 시도/ }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(JSON.parse(fetchMock.mock.calls[2]?.[1]?.body)).toEqual({ recipientPrincipalId: "operator-a" });
    expect(fetchMock.mock.calls[2]?.[1]?.headers["Idempotency-Key"]).toBe(fetchMock.mock.calls[1]?.[1]?.headers["Idempotency-Key"]);
  });
});
