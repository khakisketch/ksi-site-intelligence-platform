import { beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({ session: vi.fn(), create: vi.fn(), createWithToken: vi.fn(), list: vi.fn(), origin: vi.fn() }));
vi.mock("@/lib/core-api/session", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/core-api/session")>();
  return { ...actual, getSessionToken: mocked.session };
});
vi.mock("@/lib/core-api/observation-work-orders", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/core-api/observation-work-orders")>();
  return {
    ...actual,
    createObservationWorkOrder: mocked.create,
    createObservationWorkOrderWithToken: mocked.createWithToken,
    listObservationWorkOrders: mocked.list,
  };
});
vi.mock("@/lib/core-api/origin-guard", () => ({ isCrossSiteMutation: mocked.origin }));

import { POST } from "@/app/api/sites/[siteId]/observation-work-orders/route";

const context = { params: Promise.resolve({ siteId: "site-1" }) };

beforeEach(() => {
  vi.resetAllMocks();
  mocked.origin.mockReturnValue(false);
  mocked.session.mockResolvedValue("token");
  mocked.create.mockResolvedValue({ workOrderId: "work-order-1" });
  mocked.createWithToken.mockResolvedValue({ workOrderId: "work-order-1" });
});

describe("observation work order create BFF", () => {
  it("forwards an external creation key without placing it in the body", async () => {
    const response = await POST(new Request("http://console.test/api", {
      method: "POST",
      headers: { origin: "http://console.test", host: "console.test", "content-type": "application/json", "Idempotency-Key": "external-create-1" },
      body: JSON.stringify({ name: "외부 산출물", workAreaIds: ["wa-1"], scheduleId: null, executionMode: "EXTERNAL_RECONSTRUCTION" }),
    }) as never, context);

    expect(response.status).toBe(201);
    expect(mocked.createWithToken).toHaveBeenCalledWith(
      "site-1",
      { name: "외부 산출물", workAreaIds: ["wa-1"], scheduleId: null, executionMode: "EXTERNAL_RECONSTRUCTION" },
      "external-create-1",
      "token",
    );
    // Continuity headers are a BFF-only guard — they never enter the Core body.
    expect(mocked.createWithToken.mock.calls[0][1]).not.toHaveProperty("x-ksi-continuity-org");
  });
});
