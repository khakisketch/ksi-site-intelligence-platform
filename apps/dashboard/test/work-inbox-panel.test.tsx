/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WorkInboxPanel } from "@/app/field/inbox/WorkInboxPanel";

afterEach(() => cleanup());

describe("WorkInboxPanel", () => {
  it("explains what appears in an empty inbox and how the unread filter behaves", () => {
    render(<WorkInboxPanel initialUnreadOnly initialNextCursor={null} initialItems={[]} />);
    expect(screen.getByText(/읽지 않은 받은 업무가 없습니다/)).toBeTruthy();
    expect(screen.getByText(/전체 목록을 선택해 읽은 업무를 확인/)).toBeTruthy();
  });

  it("shows loading and failure instead of claiming the inbox is empty", async () => {
    let finishRequest: ((value: Response) => void) | undefined;
    const fetchMock = vi.fn(() => new Promise<Response>((resolve) => { finishRequest = resolve; }));
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkInboxPanel initialUnreadOnly initialNextCursor={null} initialItems={[]} />);

    fireEvent.click(screen.getByRole("button", { name: "전체" }));
    expect(screen.getByRole("status").textContent).toContain("받은 업무 목록을 불러오는 중입니다.");
    expect(screen.queryByText(/읽지 않은 받은 업무가 없습니다/)).toBeNull();

    finishRequest?.({ ok: false, status: 503 } as Response);
    expect((await screen.findByRole("alert")).textContent).toContain("받은 업무를 불러오지 못했습니다.");
    expect(screen.queryByText(/읽지 않은 받은 업무가 없습니다|받은 업무가 없습니다/)).toBeNull();
  });

  it("renders only a typed Core target route for a shared report", () => {
    render(<WorkInboxPanel initialUnreadOnly initialNextCursor={null} initialItems={[{ notificationRef: "notice-1", kind: "EXTERNAL_REPORT_SHARED", target: { kind: "EXTERNAL_REPORT", siteId: "site-a", reportRef: "report-a" }, senderPrincipalId: "operator-a", createdAt: "2026-09-10T00:00:00Z", unread: true }]} />);
    expect(screen.getByRole("link", { name: "공유된 결과 열기" }).getAttribute("href")).toBe("/sites/site-a/observations/report-a");
    expect(screen.getByText((_, element) => element?.tagName === "P" && element.textContent?.includes("operator-a") === true)).toBeTruthy();
  });

  it("retries an ambiguous read receipt with its original key", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({ ok: false, status: 504 }).mockResolvedValueOnce({ ok: true, status: 200 });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkInboxPanel initialUnreadOnly initialNextCursor={null} initialItems={[{ notificationRef: "notice-1", kind: "EXTERNAL_REPORT_SHARED", target: { kind: "EXTERNAL_REPORT", siteId: "site-a", reportRef: "report-a" }, senderPrincipalId: "operator-a", createdAt: "2026-09-10T00:00:00Z", unread: true }]} />);
    fireEvent.click(screen.getByRole("button", { name: "읽음 처리" }));
    await screen.findByRole("status");
    fireEvent.click(screen.getByRole("button", { name: "같은 읽음 요청 다시 시도" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1]?.[1]?.headers["Idempotency-Key"]).toBe(fetchMock.mock.calls[0]?.[1]?.headers["Idempotency-Key"]);
  });
});
