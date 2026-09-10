/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WorkInboxPanel } from "@/app/field/inbox/WorkInboxPanel";

afterEach(() => cleanup());

describe("WorkInboxPanel", () => {
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
