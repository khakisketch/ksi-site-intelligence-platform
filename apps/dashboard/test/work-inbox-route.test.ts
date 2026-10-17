import { beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({ session: vi.fn(), list: vi.fn(), context: vi.fn() }));
vi.mock("@/lib/core-api/session", () => ({ getSessionToken: mocked.session }));
vi.mock("@/lib/core-api/work-collaboration", () => ({ listWorkInbox: mocked.list }));
vi.mock("@/lib/work-inbox-context", () => ({ resolveWorkInboxContext: mocked.context }));

import { GET } from "@/app/api/work-inbox/route";

function request(query: string) {
  return { nextUrl: new URL(`http://console.test/api/work-inbox?${query}`) } as never;
}

beforeEach(() => {
  vi.resetAllMocks();
  mocked.session.mockResolvedValue("token");
  mocked.list.mockResolvedValue({ items: [], nextCursor: null });
  mocked.context.mockResolvedValue({});
});

describe("work inbox BFF", () => {
  it("목록에 페이지 맥락을 덧씌워 돌려준다", async () => {
    mocked.list.mockResolvedValue({ items: [{ notificationRef: "n-1" }], nextCursor: "c-1" });
    mocked.context.mockResolvedValue({ "n-1": { workName: "관측", siteName: "현장" } });

    const response = await GET(request("unreadOnly=true"));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      items: [{ notificationRef: "n-1" }],
      nextCursor: "c-1",
      contextByRef: { "n-1": { workName: "관측", siteName: "현장" } },
    });
    expect(mocked.list).toHaveBeenCalledWith({ unreadOnly: true, after: undefined });
  });

  it("맥락 확인 실패는 빈 맥락으로 접고 목록은 살린다", async () => {
    mocked.list.mockResolvedValue({ items: [{ notificationRef: "n-1" }], nextCursor: null });
    mocked.context.mockRejectedValue(new Error("denied"));

    const response = await GET(request("unreadOnly=false"));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ items: [{ notificationRef: "n-1" }], nextCursor: null, contextByRef: {} });
  });
});
