import { beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({ order: vi.fn(), site: vi.fn() }));
vi.mock("@/lib/core-api/observation-work-orders", () => ({ getObservationWorkOrder: mocked.order }));
vi.mock("@/lib/core-api/sites", () => ({ getSite: mocked.site }));

import { resolveWorkInboxContext } from "@/lib/work-inbox-context";

function assigned(notificationRef: string, workOrderId: string) {
  return { notificationRef, kind: "WORK_ORDER_ASSIGNED" as const, target: { kind: "WORK_ORDER" as const, workOrderId }, senderPrincipalId: "", createdAt: "2026-09-10T00:00:00Z", unread: true };
}

function shared(notificationRef: string, siteId: string) {
  return { notificationRef, kind: "EXTERNAL_REPORT_SHARED" as const, target: { kind: "EXTERNAL_REPORT" as const, siteId, reportRef: "report-1" }, senderPrincipalId: "", createdAt: "2026-09-10T00:00:00Z", unread: false };
}

beforeEach(() => {
  vi.resetAllMocks();
  mocked.order.mockImplementation(async (workOrderId: string) => ({ workOrderId, siteId: "site-1", name: `작업 ${workOrderId}` }));
  mocked.site.mockImplementation(async (siteId: string) => ({ siteId, name: `현장 ${siteId}` }));
});

describe("resolveWorkInboxContext", () => {
  it("같은 작업·현장은 한 번씩만 읽는다", async () => {
    const context = await resolveWorkInboxContext([assigned("n-1", "wo-1"), assigned("n-2", "wo-1"), shared("n-3", "site-1")]);

    expect(mocked.order).toHaveBeenCalledTimes(1);
    expect(mocked.site).toHaveBeenCalledTimes(1);
    expect(context["n-1"]).toEqual({ workName: "작업 wo-1", siteName: "현장 site-1" });
    expect(context["n-2"]).toEqual({ workName: "작업 wo-1", siteName: "현장 site-1" });
    expect(context["n-3"]).toEqual({ workName: null, siteName: "현장 site-1" });
  });

  it("건별 실패는 null 맥락으로 접고 전체를 깨뜨리지 않는다", async () => {
    mocked.order.mockRejectedValueOnce(new Error("denied"));
    mocked.site.mockRejectedValueOnce(new Error("denied"));

    const context = await resolveWorkInboxContext([assigned("n-1", "wo-1"), shared("n-2", "site-x")]);

    expect(context["n-1"]).toEqual({ workName: null, siteName: null });
    expect(context["n-2"]).toEqual({ workName: null, siteName: null });
  });
});
