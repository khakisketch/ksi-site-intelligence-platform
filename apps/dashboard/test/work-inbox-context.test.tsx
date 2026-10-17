/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WorkInboxPanel } from "@/app/field/inbox/WorkInboxPanel";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function assignedItem(notificationRef: string, workOrderId: string, unread = true) {
  return { notificationRef, kind: "WORK_ORDER_ASSIGNED" as const, target: { kind: "WORK_ORDER" as const, workOrderId }, senderPrincipalId: "", createdAt: "2026-09-10T00:00:00Z", unread };
}

describe("WorkInboxPanel 맥락 이름", () => {
  it("서버가 확인한 작업·현장 이름을 ID 대신 보여준다", () => {
    render(<WorkInboxPanel
      initialUnreadOnly
      initialNextCursor={null}
      initialItems={[
        { notificationRef: "notice-1", kind: "WORK_ORDER_ASSIGNED", target: { kind: "WORK_ORDER", workOrderId: "wo-1" }, senderPrincipalId: "operator-a", createdAt: "2026-09-10T00:00:00Z", unread: true },
        { notificationRef: "notice-2", kind: "EXTERNAL_REPORT_SHARED", target: { kind: "EXTERNAL_REPORT", siteId: "site-a", reportRef: "report-a" }, senderPrincipalId: "", createdAt: "2026-09-10T00:00:00Z", unread: false },
      ]}
      initialContextByRef={{
        "notice-1": { workName: "t2 관측", siteName: "한강 현장" },
        "notice-2": { workName: null, siteName: "낙동 현장" },
      }}
    />);
    expect(screen.getByText("t2 관측")).toBeTruthy();
    expect(screen.getByText("한강 현장")).toBeTruthy();
    expect(screen.getByText("낙동 현장의 공유 결과")).toBeTruthy();
    expect(document.body.textContent).not.toContain("wo-1");
  });

  it("맥락이 없으면 ID를 산문으로 찍지 않고 조용히 둔다", () => {
    render(<WorkInboxPanel
      initialUnreadOnly
      initialNextCursor={null}
      initialItems={[
        { notificationRef: "notice-9", kind: "WORK_ORDER_ASSIGNED", target: { kind: "WORK_ORDER", workOrderId: "wo-9" }, senderPrincipalId: "", createdAt: "2026-09-10T00:00:00Z", unread: true },
      ]}
    />);
    expect(document.body.textContent).not.toContain("wo-9");
    expect(screen.getByText("작업이 배정되었습니다")).toBeTruthy();
  });

  it("더 보기로 온 페이지의 이름은 이어 붙인다", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        items: [assignedItem("notice-2", "wo-2")],
        nextCursor: null,
        contextByRef: { "notice-2": { workName: "후속 관측", siteName: "낙동 현장" } },
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkInboxPanel
      initialUnreadOnly
      initialNextCursor="cursor-1"
      initialItems={[assignedItem("notice-1", "wo-1")]}
      initialContextByRef={{ "notice-1": { workName: "선행 관측", siteName: "한강 현장" } }}
    />);

    fireEvent.click(screen.getByRole("button", { name: "더 보기" }));
    await waitFor(() => expect(screen.getByText("후속 관측")).toBeTruthy());
    // 기존 페이지 맥락은 유지되고 새 페이지 맥락이 합쳐진다.
    expect(screen.getByText("선행 관측")).toBeTruthy();
    expect(screen.getByText("낙동 현장")).toBeTruthy();
    expect(screen.getByText("한강 현장")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledWith("/api/work-inbox?unreadOnly=true&after=cursor-1", { cache: "no-store" });
  });

  it("필터 전환은 목록과 맥락을 통째로 갈아끼워 낡은 맥락을 남기지 않는다", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        items: [assignedItem("notice-all", "wo-all", false)],
        nextCursor: null,
        contextByRef: { "notice-all": { workName: "전체 관측", siteName: "섬진 현장" } },
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkInboxPanel
      initialUnreadOnly
      initialNextCursor={null}
      initialItems={[assignedItem("notice-1", "wo-1")]}
      initialContextByRef={{ "notice-1": { workName: "선행 관측", siteName: "한강 현장" } }}
    />);

    fireEvent.click(screen.getByRole("button", { name: "전체" }));
    await waitFor(() => expect(screen.getByText("전체 관측")).toBeTruthy());
    // 이전 필터의 항목·맥락은 모두 사라진다(교차 대상 오염 없음).
    expect(screen.queryByText("선행 관측")).toBeNull();
    expect(screen.queryByText("한강 현장")).toBeNull();
    expect(document.body.textContent).not.toContain("wo-1");
  });

  it("긴 작업 이름도 잘라내지 않고 현장 줄과 함께 감싼다", () => {
    const longName = "[합성] 동측 절토구역 장마 이후 지형 변화 확인을 위한 매우 긴 관측 작업 이름";
    render(<WorkInboxPanel
      initialUnreadOnly
      initialNextCursor={null}
      initialItems={[
        { notificationRef: "notice-long", kind: "WORK_ORDER_ASSIGNED", target: { kind: "WORK_ORDER", workOrderId: "wo-long" }, senderPrincipalId: "", createdAt: "2026-09-10T00:00:00Z", unread: true },
      ]}
      initialContextByRef={{ "notice-long": { workName: longName, siteName: "한강 현장" } }}
    />);
    const title = screen.getByText(longName);
    expect(title.className).not.toContain("truncate");
    expect(title.className).toContain("break-words");
    expect(screen.getByText("한강 현장")).toBeTruthy();
    expect(title.closest("li")?.className).toContain("flex-col");
    expect(title.closest("li")?.className).toContain("sm:flex-row");
  });
});
